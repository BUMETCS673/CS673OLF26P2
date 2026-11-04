"""Choosing what a model sees, and keeping only the fixes that follow the rules."""

from collections.abc import Sequence

from app.ai.cards.checks import back_fits, clean_cards, normalized_fronts
from app.ai.problem_cards.prompts import MAX_FIX_OPTIONS
from app.ai.schemas import CardFixes, Diagnosis, FixOption, Verdict

MAX_SIMILAR_CARDS = 10

# How many new cards each kind needs: (fewest, most).
CARD_LIMITS = {"rewrite": (1, 1), "split": (2, 4), "contrast": (1, 2), "prerequisite": (1, 2)}
REPLACING_KINDS = frozenset({"rewrite", "split"})  # these replace the original card

def _valid_options(
    options: Sequence[FixOption], deck_fronts: set[str], added_fronts: set[str]
) -> list[dict]:
    """A card's usable options, at most one per kind. Adds their new fronts to `added_fronts`."""
    kept, kinds = [], set()
    for option in options:
        if option.kind in kinds:
            continue
        fewest, most = CARD_LIMITS[option.kind]
        cards = [
            card
            for card in clean_cards(option.cards, most, deck_fronts, added_fronts)
            if back_fits(card)
        ]
        if len(cards) < fewest:
            continue
        kinds.add(option.kind)
        added_fronts.update(normalized_fronts(card.front for card in cards))
        kept.append(
            {
                "kind": option.kind,
                "reason": option.reason.strip(),
                "cards": [card.model_dump() for card in cards],
            }
        )
        if len(kept) == MAX_FIX_OPTIONS:
            break
    return kept


def recommendations_from(
    diagnosis: Diagnosis, cards: Sequence[dict], existing_fronts: Sequence[str]
) -> list[dict]:
    """One recommendation per card with usable options, in card order."""
    by_index: dict[int, CardFixes] = {}
    for fixes in diagnosis.recommendations:
        by_index.setdefault(fixes.index, fixes)  # the first counts, if an index repeats

    # The deck's fronts are normalized once. New fronts are shared across cards, so two
    # recommendations can't add the same front.
    deck_fronts, added_fronts = normalized_fronts(existing_fronts), set()
    recommendations = []
    for index, card in enumerate(cards):
        fixes = by_index.get(index)
        options = _valid_options(fixes.options, deck_fronts, added_fronts) if fixes else []
        if options:
            recommendations.append(
                {
                    "card_id": card["id"],
                    "front": card["front"],
                    "back": card["back"],
                    "lapses": card["lapses"],
                    "options": options,
                }
            )
    return recommendations


def keep_approved(recommendations: list[dict], verdicts: dict[int, Verdict]) -> list[dict]:
    """Drop options with a card that wasn't approved, then cards with no options left.

    Verdicts are numbered across every new card, in the order this walks them.
    """
    kept, position = [], 0
    for recommendation in recommendations:
        options = []
        for option in recommendation["options"]:
            count = len(option["cards"])
            checks = [verdicts.get(position + offset) for offset in range(count)]
            position += count
            if all(check is not None and check.ok for check in checks):
                options.append(option)
        if options:
            kept.append({**recommendation, "options": options})
    return kept
