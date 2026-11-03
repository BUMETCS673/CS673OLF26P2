"""Starting card generation, which runs as a background job, and reading its batches."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.cards.suggestions import suggest_deck_topics
from app.ai.models import AIRateLimited, AIUnavailable, Role, load_chat_model
from app.ai.schemas import CardDraft
from app.ai.tracing import labelled_trace
from app.ai.usage import RunUsage
from app.core.errors import BudgetExceeded, InvalidRequest, NotAvailable, NotFound
from app.core.settings import Settings
from app.models import AiGeneration, Card, Job, User, utcnow
from app.models.document import READY
from app.models.job import EMBED_CARDS, GENERATE_CARDS
from app.repositories.cards import CardRepository
from app.repositories.decks import DeckRepository
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
from app.services.budget import BUDGET_WINDOW, SUGGESTIONS, BudgetService
from app.services.decks import DECK_NOT_FOUND
from app.services.materials import MATERIAL_NOT_FOUND

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
        decks: DeckRepository,
        documents: DocumentRepository,
        generations: GenerationRepository,
        jobs: JobRepository,
        cards: CardRepository,
        budget: BudgetService,
        settings: Settings,
    ):
        self.session = session
        self.decks = decks
        self.documents = documents
        self.generations = generations
        self.jobs = jobs
        self.cards = cards
        self.budget = budget
        self.settings = settings

    async def _check_caps(self, user_id: int) -> None:
        limit = self.settings.ai_daily_limit
        since = utcnow() - BUDGET_WINDOW
        finished = await self.generations.count_with_cards_since(user_id, since)
        # Jobs still waiting count too, or queueing many at once would get past the limit.
        waiting = await self.jobs.count_unfinished(user_id, GENERATE_CARDS)
        if finished + waiting >= limit:
            raise BudgetExceeded(
                f"You've reached the limit of {limit} AI generations in 24 hours. Try again later."
            )
        if not await self.budget.within_model_limits(WORST_CASE_CALLS):
            raise BudgetExceeded(SITE_CAP)

    async def start(self, deck_id: int, user: User, body: GenerateRequest) -> int:
        """Queue a run and return its job's id. Failures from here on are saved on the job."""
        if await self.decks.get_owned(deck_id, user.id) is None:
            raise NotFound(DECK_NOT_FOUND)
        file_name = None
        if body.mode == FILE:
            document = await self.documents.get_owned(body.document_id, user.id)
            if document is None:
                raise NotFound(MATERIAL_NOT_FOUND)
            if document.status != READY:
                raise InvalidRequest("That file isn't ready yet.", "document_id")
            file_name = document.filename
        await self._check_caps(user.id)

        job = await self.jobs.add(
            Job(
                user_id=user.id,
                kind=GENERATE_CARDS,
                payload={**body.model_dump(), "deck_id": deck_id, "file_name": file_name},
            )
        )
        await self.session.commit()
        return job.id

    async def _locked(self, generation_id: int, user: User) -> AiGeneration:
        generation = await self.generations.get_owned(generation_id, user.id, lock=True)
        if generation is None:
            raise NotFound(GENERATION_NOT_FOUND)
        return generation

    def _decide(self, generation: AiGeneration, indexes: list[int], status: str) -> list[int]:
        """Mark each pending index, returning those that changed, since decisions are final.

        A new list is assigned, because SQLAlchemy doesn't notice a change inside a JSON value.
        """
        if any(not 0 <= index < len(generation.candidates) for index in indexes):
            raise InvalidRequest(BAD_INDEXES, "indexes")
        changed = [
            index
            for index in sorted(set(indexes))
            if generation.candidates[index]["status"] == PENDING
        ]
        generation.candidates = [
            {**candidate, "status": status} if index in changed else candidate
            for index, candidate in enumerate(generation.candidates)
        ]
        return changed

    async def accept(self, generation_id: int, user: User, indexes: list[int]) -> Accepted:
        """The cards and the job that embeds them commit together, so accepting stays instant."""
        generation = await self._locked(generation_id, user)
        changed = self._decide(generation, indexes, ACCEPTED)
        cards = await self.cards.add_many(
            [
                Card(
                    deck_id=generation.deck_id,
                    front=generation.candidates[index]["front"],
                    back=generation.candidates[index]["back"],
                    origin="ai",
                    generation_id=generation.id,
                )
                for index in changed
            ]
        )
        if cards:
            await self.jobs.add(
                Job(
                    user_id=user.id,
                    kind=EMBED_CARDS,
                    payload={"card_ids": [card.id for card in cards]},
                )
            )
        await self.session.commit()
        return Accepted(
            cards=[CardRead.model_validate(card) for card in cards],
            generation=GenerationRead.model_validate(generation),
        )

    async def reject(self, generation_id: int, user: User, indexes: list[int]) -> GenerationRead:
        generation = await self._locked(generation_id, user)
        self._decide(generation, indexes, REJECTED)
        await self.session.commit()
        return GenerationRead.model_validate(generation)

    async def suggest(self, deck_id: int, user: User) -> list[str]:
        """Topics to learn next. Failures show, since the learner asked for these."""
        user_id = user.id
        deck = await self.decks.get_owned(deck_id, user_id)
        if deck is None:
            raise NotFound(DECK_NOT_FOUND)
        limit = self.settings.ai_suggestions_user_daily_limit
        if await self.budget.user_feature_calls(SUGGESTIONS, user_id) >= limit:
            raise BudgetExceeded(f"You've reached the limit of {limit} suggestions in 24 hours.")
        if not await self.budget.within_model_limits({Role.WRITER: 1}):
            raise BudgetExceeded(SITE_CAP)
        newest = await self.cards.newest_in_deck(deck_id, SUGGESTION_CONTEXT)
        existing = [CardDraft(front=card.front, back=card.back) for card in newest]
        name, description = deck.name, deck.description
        # A model call can take a while, and mustn't hold a database connection meanwhile.
        await self.session.close()

        usage = RunUsage()
        try:
            model = load_chat_model(Role.WRITER, self.settings, usage, learner_waiting=True)
            async with labelled_trace(SUGGESTIONS, user_id, deck_id=deck_id):
                return await suggest_deck_topics(model, name, description, existing)
        except AIRateLimited as error:
            raise BudgetExceeded(error.message) from None
        except AIUnavailable as error:
            raise NotAvailable(error.message) from None
        finally:
            self.budget.record(SUGGESTIONS, user_id, deck_id, usage)
            await self.session.commit()

    async def get(self, generation_id: int, user: User) -> GenerationRead:
        generation = await self.generations.get_owned(generation_id, user.id)
        if generation is None:
            raise NotFound(GENERATION_NOT_FOUND)
        return GenerationRead.model_validate(generation)
