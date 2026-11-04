"""What stays fixed during a turn. It isn't saved in the checkpoint, so models never are."""

import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from functools import cached_property

from langchain_core.language_models import BaseChatModel

from app.ai.cards.checks import normalized_fronts
from app.ai.cards.existing import FindExisting, no_existing_cards

_WORD = re.compile(r"\w+")


def words(text: str) -> set[str]:
    return set(_WORD.findall(text.lower()))


async def no_similar_cards(_query: str) -> list[dict]:
    return []


@dataclass(frozen=True, kw_only=True)
class TutorContext:
    writer: BaseChatModel
    judge: BaseChatModel
    deck_name: str
    cards: list[dict]  # {"front", "back", "lapses"}, for this deck only
    # This deck's cards closest in meaning to a query. Empty if the search can't run.
    find_similar: Callable[[str], Awaitable[list[dict]]] = no_similar_cards
    find_existing: FindExisting = no_existing_cards  # the deck's cards a proposal might repeat

    # Worked out on first use and kept for the turn, since the tools can run several times in one.
    @cached_property
    def card_words(self) -> list[set[str]]:
        """Each card's words, in the order of `cards`."""
        return [words(f"{card['front']} {card['back']}") for card in self.cards]

    @cached_property
    def taken_fronts(self) -> set[str]:
        return normalized_fronts(card["front"] for card in self.cards)
