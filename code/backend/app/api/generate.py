"""Generating cards with AI - B3 (Duc).

The blueprint is registered by `app/api/__init__.py`. Like `cards_bp`, it has no
url_prefix:

    POST /api/decks/<deck_id>/generate
         {mode: "prompt", count, prompt}
         {mode: "file", count, file: {name, mime_type, data}, focus?}
         {mode: "suggest", count}
      -> 201 Generation    404, 400, 422 + field, 429 rate_limited, 503 ai_unavailable

Contract C2 in code/plans/ITERATION_3_PLAN.md, which also fixes the order of the checks:
ownership, the JSON body, the fields top to bottom, the daily caps, then the provider.
The logic is in `app/services/generation.py`. A request that fails at the provider saves no batch,
so it doesn't use the learner's cap, but its calls still count toward the model's limit.
"""

# Step 0a: the empty blueprint and the docstring.
# AI Utilization: ~100% of that code
# AI Tools Used: Claude Code (Claude Opus 5.5)
# AI-Assisted Activities:
#   Blueprint scaffolding
#   Documentation
# Human role: plan approval, code review, and hands-on testing by Miles Cameron.
#
# B3: the generate route.
# AI Utilization: ~100% of that code
# AI Tools Used: Claude Code (Claude Opus 5.5)
# AI-Assisted Activities:
#   API endpoint development
#   Input validation and daily caps
#   Documentation
# Human role: plan review, code review, and CI verification by Duc Anh Nguyen.
#
# Iteration 3 refactor: the prompt and focus checks moved to app/api/validation.py.
# AI Utilization: ~100% of that change
# AI Tools Used: Claude Code (Claude Opus 5.5)
# AI-Assisted Activities:
#   Refactoring
# Human role: plan approval and code review by Duc Anh Nguyen.

import base64
import binascii

from flask import Blueprint, current_app, jsonify, request
from flask_login import current_user, login_required

from app.ai.provider import Attachment
from app.api.decks import own_deck_or_404
from app.api.validation import optional_text, required_text
from app.errors import json_object, validation_error
from app.services.generation import GenerationRequest, generate_cards

generate_bp = Blueprint("generate", __name__)

BODY_MAX = 6 * 1024 * 1024        # this route only; every other route keeps MAX_CONTENT_LENGTH
FILE_MAX = 4 * 1024 * 1024        # decoded bytes
TEXT_FILE_MAX = 100_000           # characters, after decoding
PROMPT_MAX = 2000
FOCUS_MAX = 500
FILE_NAME_MAX = 255
SUGGEST_MIN_CARDS = 10

MODES = ("prompt", "file", "suggest")
PDF = "application/pdf"
FILE_TYPES = (PDF, "text/plain", "text/markdown")

UNSUPPORTED_FILE = "Only PDF, TXT and MD files are supported. Save other documents as a PDF first."


def _valid_mode(body: dict) -> str:
    mode = body.get("mode")
    if mode not in MODES:
        raise validation_error("mode must be one of: prompt, file, suggest.", "mode")
    return mode


def _valid_count(body: dict) -> int:
    count = body.get("count")
    limit = current_app.config["AI_MAX_CARDS"]
    # `type() is int`, not isinstance: True is an int to Python, and the contract refuses it.
    if type(count) is not int or not 1 <= count <= limit:
        raise validation_error(f"count must be a whole number from 1 to {limit}.", "count")
    return count


def _valid_file(body: dict) -> tuple[str, str | None, Attachment | None]:
    """The file's name, then its text (TXT or MD) or its attachment (PDF)."""
    file = body.get("file")
    if not isinstance(file, dict) or not all(
        isinstance(file.get(key), str) for key in ("name", "mime_type", "data")
    ):
        raise validation_error("file is required.", "file")
    if len(file["name"]) > FILE_NAME_MAX:
        raise validation_error(
            f"The file name must be at most {FILE_NAME_MAX} characters.", "file"
        )
    mime_type = file["mime_type"]
    if mime_type not in FILE_TYPES:
        raise validation_error(UNSUPPORTED_FILE, "file")

    try:
        data = base64.b64decode(file["data"], validate=True)
    except (binascii.Error, ValueError):
        data = b""
    if not data:
        raise validation_error("That file couldn't be read.", "file")
    if len(data) > FILE_MAX:
        raise validation_error("The file must be 4 MB or smaller.", "file")

    if mime_type == PDF:
        if not data.startswith(b"%PDF-"):
            raise validation_error("That file isn't a valid PDF.", "file")
        return file["name"], None, Attachment(mime_type=PDF, data=data)

    try:
        text = data.decode("utf-8-sig")  # a byte-order mark doesn't count against the file
    except UnicodeDecodeError:
        raise validation_error("That text file isn't UTF-8 text.", "file") from None
    if len(text) > TEXT_FILE_MAX:
        raise validation_error(
            "That text file is too long. Split it into files under 100,000 characters.", "file"
        )
    return file["name"], text, None


@generate_bp.post("/decks/<int:deck_id>/generate")
@login_required
def generate(deck_id):
    # Before anything reads the body. Flask 3.1 lets one route raise its own limit.
    request.max_content_length = BODY_MAX

    deck = own_deck_or_404(deck_id)
    body = json_object()

    mode = _valid_mode(body)
    count = _valid_count(body)
    prompt = file_name = file_text = attachment = focus = None
    if mode == "prompt":
        prompt = required_text(body.get("prompt"), "prompt", PROMPT_MAX)
    elif mode == "file":
        file_name, file_text, attachment = _valid_file(body)
        focus = optional_text(body.get("focus"), "focus", FOCUS_MAX)
    elif mode == "suggest" and deck.card_count < SUGGEST_MIN_CARDS:
        raise validation_error(
            "Suggest more content needs at least 10 cards in the deck.", "mode"
        )

    generation = generate_cards(deck, current_user.id, GenerationRequest(
        mode=mode,
        count=count,
        prompt=prompt,
        file_name=file_name,
        file_text=file_text,
        attachment=attachment,
        focus=focus,
    ))
    return jsonify(generation.to_dict()), 201
