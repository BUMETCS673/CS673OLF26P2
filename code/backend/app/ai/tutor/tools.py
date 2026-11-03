"""The tools the tutor's model can call. They only see the cards in the turn's context, which the
service loads for the signed-in learner's deck, so the model can't choose a deck or a user.
"""

import heapq
from itertools import zip_longest

from langchain_core.tools import tool
from langgraph.runtime import get_runtime

from app.ai.prompting import json_block
from app.ai.schemas import CardDraft
from app.ai.tutor.context import TutorContext, words

MAX_TOOL_CARDS = 10


def _as_result(cards: list[dict]) -> str:
    # In the tags the model's rules say to treat as material.
    return json_block("cards", cards[:MAX_TOOL_CARDS])


def _word_matches(context: TutorContext, query: str) -> list[dict]:
    """The cards sharing the most words with `query`. Also finds cards without a vector yet.

    Only the top MAX_TOOL_CARDS, which is all a result shows. Ties keep deck order.
    """
    wanted = words(query)
    scored = (
        (len(wanted & card_words), card)
        for card, card_words in zip(context.cards, context.card_words, strict=True)
    )
    best = heapq.nlargest(
        MAX_TOOL_CARDS, (item for item in scored if item[0] > 0), key=lambda item: item[0]
    )
    return [card for _, card in best]


def _interleaved(first: list[dict], second: list[dict]) -> list[dict]:
    """Taking turns, so a limit keeps the best of both lists. A card found by both appears once."""
    merged: dict[str, dict] = {}
    for pair in zip_longest(first, second):
        for card in pair:
            if card:
                merged.setdefault(card["front"], card)
    return list(merged.values())


@tool
async def search_deck(query: str) -> str:
    """Find the deck's cards closest to a query, in meaning or in wording."""
    context = get_runtime(TutorContext).context
    similar = await context.find_similar(query)
    return _as_result(_interleaved(similar, _word_matches(context, query)))


@tool
async def weak_cards() -> str:
    """Get the deck's cards the learner forgets most."""
    cards = get_runtime(TutorContext).context.cards
    forgotten = (card for card in cards if card["lapses"] > 0)
    return _as_result(heapq.nlargest(MAX_TOOL_CARDS, forgotten, key=lambda card: card["lapses"]))


@tool(response_format="content_and_artifact", return_direct=True)
async def propose_cards(cards: list[CardDraft]) -> tuple[str, list[dict]]:
    """Suggest new cards for the learner to accept or decline. This ends your turn."""
    # Nothing is saved here: the graph checks the cards and the learner decides.
    return "The cards were sent for checking.", [card.model_dump() for card in cards]


TUTOR_TOOLS = [search_deck, weak_cards, propose_cards]
