"""Putting untrusted text into prompts safely."""

import hashlib
import json
import re
from collections.abc import Sequence

from app.ai.schemas import CardDraft

EXISTING_JSON_MAX = 30_000  # characters of JSON inside <existing_cards>

_CLOSING_TAG = re.compile(  # compiled once at import reused for every prompt
    # a lookahead matches only the "<" of our closing tags so only it gets replaced
    r"<(?=/\s*(?:source|reference|focus|existing_cards|topic|candidates|rejected_cards|kept_cards"
    r"|cards|deck|conversation)\s*>)",
    re.IGNORECASE,  # "</SOURCE>" counts too
)


def version_of(*texts: str) -> str:
    """A short hash of prompt text, so editing a prompt can't leave its version stale."""
    # a "\0" separator makes ("ab", "c") and ("a", "bc") hash differently
    return hashlib.sha256("\0".join(texts).encode()).hexdigest()[:12]


def escape_tags(text: str) -> str:
    """Put a backslash after the `<` of our closing tags, so text can't end its block early."""
    # "</source>" becomes "<\/source>" which the model treats as plain text
    return _CLOSING_TAG.sub(r"<\\", text)


def block(tag: str, content: str) -> str:
    return f"<{tag}>\n{content}\n</{tag}>"  # trusted content only so no escaping here


def text_block(tag: str, text: str) -> str:
    return block(tag, escape_tags(text))  # for anything a learner or a file wrote


def json_block(tag: str, items: list[dict]) -> str:
    # ensure_ascii=False keeps accents readable and saves tokens over \u escapes
    return text_block(tag, json.dumps(items, ensure_ascii=False))


def existing_json(existing: Sequence[CardDraft]) -> str:
    """The newest cards as a JSON list, stopping before it passes EXISTING_JSON_MAX."""
    items: list[str] = []
    length = len("[]")  # the brackets count toward the cap
    for card in existing:  # newest first so the cap drops the oldest
        item = escape_tags(json.dumps(card.model_dump(), ensure_ascii=False))
        added = len(item) + (len(", ") if items else 0)  # the separator before all but the first
        if length + added > EXISTING_JSON_MAX:  # whole cards only never a cut-off item
            break
        items.append(item)
        length += added
    return "[" + ", ".join(items) + "]"  # built by hand so the length is known as it grows
