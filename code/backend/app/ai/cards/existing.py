"""The deck's cards a judge compares new ones against.

A judge only needs the cards a new one might repeat, so it gets each candidate's closest cards by
meaning, not the whole deck. Cards without a vector yet are the newest, and so the likeliest
repeats of a fresh batch, so they come along too.
"""

from collections.abc import Awaitable, Callable, Sequence
from contextlib import AbstractAsyncContextManager

from langchain_core.stores import ByteStore

from app.ai.knowledge.indexing import with_embedding_cache
from app.ai.models import AIRateLimited, AIUnavailable, Role, ai_errors, load_embeddings, model_name
from app.ai.schemas import CardDraft
from app.ai.usage import RunUsage
from app.core.settings import Settings
from app.repositories.cards import CardRepository

NEAREST_PER_CARD = 3
NEWEST_UNEMBEDDED = 10
FALLBACK_CARDS = 20  # the newest, when the candidates can't be embedded

FindExisting = Callable[[Sequence[CardDraft]], Awaitable[Sequence[CardDraft]]]
OpenCards = Callable[[], AbstractAsyncContextManager[CardRepository]]


async def no_existing_cards(_drafts: Sequence[CardDraft]) -> Sequence[CardDraft]:
    return ()


def existing_card_finder(
    deck_id: int,
    open_cards: OpenCards,
    settings: Settings,
    usage: RunUsage,
    *,
    cache: ByteStore | None = None,
    learner_waiting: bool = False,
) -> FindExisting:
    """Embeds before opening the repository, so no connection waits on the model.

    With `cache`, an accepted card's embedding job reuses the vector made here.
    """
    model = model_name(Role.EMBEDDER, settings)
    try:
        embeddings = load_embeddings(settings, usage, learner_waiting=learner_waiting)
    except AIUnavailable:
        embeddings = None
    if embeddings is not None and cache is not None:
        embeddings = with_embedding_cache(embeddings, cache, model)

    async def find_existing(drafts: Sequence[CardDraft]) -> Sequence[CardDraft]:
        vectors = None
        if embeddings is not None:
            try:
                with ai_errors():
                    # As documents, the way the cards were embedded, so both sides compare alike.
                    vectors = await embeddings.aembed_documents(
                        [f"{draft.front} {draft.back}" for draft in drafts]
                    )
            except (AIRateLimited, AIUnavailable):
                pass  # without vectors, the newest cards stand in below
        async with open_cards() as cards:
            if vectors is None:
                rows = await cards.newest_in_deck(deck_id, FALLBACK_CARDS)
            else:
                rows = await cards.likely_repeats(
                    deck_id, vectors, model, NEAREST_PER_CARD, NEWEST_UNEMBEDDED
                )
        return [CardDraft(front=row.front, back=row.back) for row in rows]

    return find_existing
