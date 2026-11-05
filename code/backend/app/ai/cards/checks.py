"""Checks on a model's cards that need no model, so failing them costs no judge call."""

import re
import unicodedata
from collections.abc import Container, Iterable, Sequence

from app.ai.cards.prompts import BACK_MAX_WORDS
from app.ai.schemas import CardDraft

TEXT_MAX = 2000  # the same limit as a card's side

# Whitespace and these marks come off both ends. Nothing else is removed.
_END_MARKS = " .,;:!?¿¡…'\"‘’“”«»()[]{}"
_WHITESPACE = re.compile(r"\s+")  # compiled once


def normalize_front(text: str) -> str:
    """A form for comparing fronts, so case, spacing and end punctuation don't hide a repeat."""
    # NFC makes "é" as one character equal "e" plus an accent
    text = unicodedata.normalize("NFC", text).lower()
    return _WHITESPACE.sub(" ", text).strip(_END_MARKS)  # runs of spaces become one


def _gives_answer_away(front: str, back: str) -> bool:
    # the back as a whole word in the front escaped so its punctuation isn't regex syntax
    return re.search(r"(?<!\w)" + re.escape(back) + r"(?!\w)", front) is not None


def normalized_fronts(fronts: Iterable[str]) -> set[str]:
    """For `clean_cards`. Built once per deck, since normalizing every front is the costly part."""
    return {normalize_front(front) for front in fronts}


def clean_cards(
    cards: Sequence[CardDraft], limit: int, *taken: Container[str]
) -> list[CardDraft]:
    """Usable cards, up to `limit`, leaving out empty ones, repeats and those that give it away.

    `taken` holds `normalized_fronts` sets, checked as they are, so a large deck isn't copied.
    """
    seen: set[str] = set()  # this batch's fronts
    kept: list[CardDraft] = []
    for card in cards:
        if len(kept) >= limit:  # stop once there are enough without looking at the rest
            break
        front, back = card.front.strip(), card.back.strip()
        # empty or too long to save as a card side
        if not front or not back or len(front) > TEXT_MAX or len(back) > TEXT_MAX:
            continue
        normal_front, normal_back = normalize_front(front), normalize_front(back)
        if not normal_back or _gives_answer_away(normal_front, normal_back):  # e.g "?" only
            continue
        # O(1) set lookups for repeats in this batch or in any taken set
        if normal_front in seen or any(normal_front in fronts for fronts in taken):
            continue
        seen.add(normal_front)
        kept.append(CardDraft(front=front, back=back))  # the stripped text not the raw reply
    return kept


def back_fits(card: CardDraft) -> bool:
    return len(card.back.split()) <= BACK_MAX_WORDS  # words split on any whitespace
