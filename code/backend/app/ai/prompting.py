"""Putting untrusted text into prompts safely."""

import hashlib
import json
import re
from collections.abc import Sequence

from app.ai.schemas import CardDraft

EXISTING_CARDS = 200  # newest cards sent along, so a run can avoid repeating them
EXISTING_JSON_MAX = 30_000  # characters of JSON inside <existing_cards>

_CLOSING_TAG = re.compile(
    r"<(?=/\s*(?:source|reference|focus|existing_cards|topic|candidates|rejected_cards|kept_cards"
    r"|cards|deck|conversation)\s*>)",
    re.IGNORECASE,
)


def version_of(*texts: str) -> str:
    """A short hash of prompt text, so editing a prompt can't leave its version stale."""
    return hashlib.sha256("\0".join(texts).encode()).hexdigest()[:12]


def escape_tags(text: str) -> str:
    """Put a backslash after the `<` of our closing tags, so text can't end its block early."""
    return _CLOSING_TAG.sub(r"<\\", text)


def block(tag: str, content: str) -> str:
    return f"<{tag}>\n{content}\n</{tag}>"


def text_block(tag: str, text: str) -> str:
    return block(tag, escape_tags(text))


def json_block(tag: str, items: list[dict]) -> str:
    return text_block(tag, json.dumps(items, ensure_ascii=False))


def existing_json(existing: Sequence[CardDraft]) -> str:
    """The newest cards as a JSON list, stopping before it passes EXISTING_JSON_MAX."""
    items: list[str] = []
    length = len("[]")
    for card in existing:
        item = escape_tags(json.dumps(card.model_dump(), ensure_ascii=False))
        added = len(item) + (len(", ") if items else 0)
        if length + added > EXISTING_JSON_MAX:
            break
        items.append(item)
        length += added
    return "[" + ", ".join(items) + "]"
