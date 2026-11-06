"""Starting card generation, which runs as a background job, and reading its batches."""

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.cards.suggestions import suggest_deck_topics
from app.ai.models import AIRateLimited, AIUnavailable, Role, load_chat_model
from app.ai.schemas import CardDraft
from app.ai.tracing import labelled_trace
from app.ai.usage import RunUsage
from app.core.errors import BudgetExceeded, InvalidRequest, NotAvailable, found
from app.core.settings import Settings
from app.models import AiGeneration, Card, Deck, Job, User, utcnow
from app.models.document import READY
from app.models.job import GENERATE_CARDS
from app.repositories.cards import CardRepository
from app.repositories.documents import DocumentRepository
from app.repositories.generations import GenerationRepository
from app.repositories.jobs import JobRepository
from app.schemas.cards import CardRead
from app.schemas.generations import (
    BAD_INDEXES,
    FILE,
    Accepted,
    GenerateRequest,
    GenerationRead,
)
from app.services.budget import BUDGET_WINDOW, SUGGESTIONS, USER, BudgetService
from app.services.materials import MATERIAL_NOT_FOUND

logger = logging.getLogger(__name__)

GENERATION_NOT_FOUND = "Generation not found"
SITE_CAP = "AI generation has hit today's limit for the whole site. Try again later."

# The most one run can spend: a first write, another after its one search, and one repair.
WORST_CASE_CALLS = {Role.WRITER: 3, Role.JUDGE: 2, Role.EMBEDDER: 1}

PENDING = "pending"
ACCEPTED = "accepted"
REJECTED = "rejected"
SUGGESTION_CONTEXT = 200  # newest cards sent along, so suggestions can avoid what's covered


class GenerationService:
    def __init__(
        self,
        session: AsyncSession,
        documents: DocumentRepository,
        generations: GenerationRepository,
        jobs: JobRepository,
        cards: CardRepository,
        budget: BudgetService,
        settings: Settings,
    ):
        self.session = session  # one request's transaction so nothing saves until commit
        self.documents = documents
        self.generations = generations
        self.jobs = jobs
        self.cards = cards
        self.budget = budget
        self.settings = settings

    async def _check_caps(self, user_id: int) -> None:
        # Step 1: count the user's runs in 24 hours Jobs still waiting count too or queueing
        # many at once would get past the limit
        limit = self.settings.ai_daily_limit
        since = utcnow() - BUDGET_WINDOW  # rolling 24 hours not a calendar day
        # only runs that produced cards count so a failed run doesn't use up the day
        finished = await self.generations.count_with_cards_since(user_id, since)
        waiting = await self.jobs.count_unfinished(user_id, GENERATE_CARDS)  # queued or running
        logger.info(
            "generation caps checked",
            extra={"user_id": user_id, "finished": finished, "waiting": waiting, "limit": limit},
        )
        if finished + waiting >= limit:
            logger.info("generation refused", extra={"user_id": user_id, "limit": "user"})
            raise BudgetExceeded(  # 429 to the client
                f"You've reached the limit of {limit} AI generations in 24 hours. Try again later."
            )

        # Step 2: refuse if the models have no room left today for a run's worst case
        # judged=WRITER makes the judge a stronger model than the writer it checks
        if not await self.budget.within_model_limits(WORST_CASE_CALLS, judged=Role.WRITER):
            logger.info("generation refused", extra={"user_id": user_id, "limit": "site"})
            raise BudgetExceeded(SITE_CAP)  # 429 now instead of a failed job later

    async def start(self, deck: Deck, user: User, body: GenerateRequest) -> int:
        """Queue a run and return its job's id. Failures from here on are saved on the job."""
        # Step 1: in file mode check the file is the learner's and finished processing
        file_name = None
        if body.mode == FILE:
            document = found(
                await self.documents.get_owned(body.document_id, user.id), MATERIAL_NOT_FOUND
            )
            if document.status != READY:  # still being indexed or failed
                logger.info(
                    "generation refused",
                    extra={"document_id": document.id, "reason": "file_not_ready"},
                )
                raise InvalidRequest("That file isn't ready yet.", "document_id")  # 422
            file_name = document.filename  # copied so the job doesn't need the row later

        # Step 2: check the daily limits
        await self._check_caps(user.id)

        # Step 3: queue the run as a job for the worker to make the AI calls
        job = await self.jobs.add(
            Job(
                user_id=user.id,
                kind=GENERATE_CARDS,
                # everything the worker needs so it runs without this request
                payload={**body.model_dump(), "deck_id": deck.id, "file_name": file_name},
            )
        )
        await self.session.commit()  # the relay hands the outbox job to the queue after this commit
        logger.info(
            "generation queued",
            extra={
                "deck_id": deck.id,
                "job_id": job.id,
                "mode": body.mode,
                "count": body.count,
            },
        )
        return job.id  # 202 to the client which follows the job's live events

    async def _locked(self, generation_id: int, user: User) -> AiGeneration:
        # SELECT ... FOR UPDATE runs concurrent decisions on one batch one after another
        return found(
            await self.generations.get_owned(generation_id, user.id, lock=True),
            GENERATION_NOT_FOUND,
        )

    def _decide(self, generation: AiGeneration, indexes: list[int], status: str) -> list[int]:
        """Mark each pending index, returning those that changed, since decisions are final.

        A new list is assigned, because SQLAlchemy doesn't notice a change inside a JSON value.
        """
        # Step 1: refuse an index outside the batch
        if any(not 0 <= index < len(generation.candidates) for index in indexes):
            raise InvalidRequest(BAD_INDEXES, "indexes")  # 422 and nothing changes
        # Step 2: pick the indexes still pending Ones already decided stay as they are
        changed = [
            index
            for index in sorted(set(indexes))  # a set so a repeated index counts once
            if generation.candidates[index]["status"] == PENDING  # decisions are final
        ]
        # Step 3: mark them in a new list
        marked = set(changed)  # constant-time lookups while rebuilding the list
        generation.candidates = [  # reassigned so SQLAlchemy sees the JSON change
            {**candidate, "status": status} if index in marked else candidate
            for index, candidate in enumerate(generation.candidates)
        ]
        return changed  # only these become cards so a repeat accept adds nothing

    async def accept(self, generation_id: int, user: User, indexes: list[int]) -> Accepted:
        """The cards and the job that embeds them commit together, so accepting stays instant."""
        # Step 1: lock the batch so two accepts can't add the same card twice
        generation = await self._locked(generation_id, user)
        # Step 2: mark the chosen candidates accepted
        changed = self._decide(generation, indexes, ACCEPTED)
        # Step 3: add a card for each newly accepted candidate
        cards = await self.cards.add_many(  # one INSERT for all of them
            [
                Card(
                    deck_id=generation.deck_id,
                    front=generation.candidates[index]["front"],  # server's copy not the request
                    back=generation.candidates[index]["back"],
                    origin="ai",  # marks it as AI-written in the deck
                    generation_id=generation.id,  # lets a report find the material it came from
                )
                for index in changed
            ]
        )
        # Step 4: queue their embedding in the same commit
        if cards:  # nothing new means no empty job
            # one job for every card so the embedder takes them in one batch call
            await self.jobs.queue_card_embedding(user.id, [card.id for card in cards])
        await self.session.commit()  # cards and their job together or neither
        logger.info(
            "candidates accepted",
            extra={"generation_id": generation.id, "asked": len(indexes), "added": len(cards)},
        )
        return Accepted(  # 201 with the new cards and the batch's updated statuses
            cards=[CardRead.model_validate(card) for card in cards],
            generation=GenerationRead.model_validate(generation),
        )

    async def reject(self, generation_id: int, user: User, indexes: list[int]) -> GenerationRead:
        # Step 1: lock the batch then mark the chosen candidates rejected
        generation = await self._locked(generation_id, user)
        changed = self._decide(generation, indexes, REJECTED)  # no cards made only statuses
        await self.session.commit()
        logger.info(
            "candidates rejected",
            extra={"generation_id": generation.id, "asked": len(indexes), "changed": len(changed)},
        )
        return GenerationRead.model_validate(generation)

    async def suggest(self, deck: Deck, user: User) -> list[str]:
        """Topics to learn next. Failures show, since the learner asked for these."""
        user_id, deck_id = user.id, deck.id  # plain values stay safe after the session closes below
        logger.info("suggestions started", extra={"user_id": user_id, "deck_id": deck_id})

        # Step 1: check the learner's daily limit and pick a helper model with room left
        limit = self.settings.ai_suggestions_user_daily_limit
        reached, models = await self.budget.limit_reached(
            SUGGESTIONS, user_id, {Role.HELPER: 1}, user_limit=limit  # costs one helper call
        )
        if reached:
            logger.info("suggestions refused", extra={"deck_id": deck_id, "limit": reached})
        if reached == USER:
            raise BudgetExceeded(f"You've reached the limit of {limit} suggestions in 24 hours.")
        if reached:  # SITE means the whole site's limit or no helper model has room
            raise BudgetExceeded(SITE_CAP)  # 429 to the client

        # Step 2: read the deck's newest cards so the model suggests topics they don't cover
        # capped at the newest 200 so a big deck doesn't blow up the prompt
        newest = await self.cards.newest_in_deck(deck_id, SUGGESTION_CONTEXT)
        existing = [CardDraft(front=card.front, back=card.back) for card in newest]
        name, description = deck.name, deck.description  # copied because the deck detaches on close
        logger.info("suggestions context read", extra={"deck_id": deck_id, "cards": len(existing)})
        # A model call can take a while, and mustn't hold a database connection meanwhile.
        await self.session.close()  # back to the pool so a slow model can't starve other requests

        # Step 3: ask the helper model falling back down its chain if a model fails
        usage = RunUsage()  # callbacks count each call's model and tokens into this
        try:
            model = load_chat_model(
                # learner_waiting waits at most 12 s on the rate limiter then falls back
                Role.HELPER, self.settings, usage, learner_waiting=True, models=models
            )
            # tags the LangSmith trace with the feature, user and deck
            async with labelled_trace(SUGGESTIONS, user_id, deck_id=deck_id):
                topics = await suggest_deck_topics(model, name, description, existing)
            logger.info("suggestions done", extra={"deck_id": deck_id, "topics": len(topics)})
            return topics  # 200 with the router wrapping them in a topics object
        # Step 4: turn AI failures into errors the learner sees
        except AIRateLimited as error:  # every model in the chain hit its quota
            logger.info("suggestions failed", extra={"deck_id": deck_id, "reason": "rate_limited"})
            raise BudgetExceeded(error.message) from None  # 429
        except AIUnavailable as error:  # timeouts, server errors or a reply that didn't parse
            logger.info("suggestions failed", extra={"deck_id": deck_id, "reason": "unavailable"})
            raise NotAvailable(error.message) from None  # 503
        # Step 5: save what the calls spent whether they worked or not
        finally:
            self.budget.record(SUGGESTIONS, user_id, deck_id, usage)  # a failed call still costs
            await self.session.commit()  # the session reopens a connection just for this

    async def get(self, generation_id: int, user: User) -> GenerationRead:
        generation = found(
            await self.generations.get_owned(generation_id, user.id), GENERATION_NOT_FOUND
        )
        return GenerationRead.model_validate(generation)
