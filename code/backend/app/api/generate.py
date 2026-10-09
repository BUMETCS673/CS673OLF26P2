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
A request that fails at the provider saves nothing, so it doesn't count toward either cap.
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

import base64
import binascii
import time
from datetime import timedelta

from flask import Blueprint, current_app, jsonify, request
from flask_login import current_user, login_required
from sqlalchemy import func, select

from app.ai.cleanup import clean_drafts
from app.ai.prompts import build_prompt
from app.ai.provider import AIRateLimited, AIUnavailable, Attachment, CardDraft, get_provider
from app.errors import ApiError, json_object, not_found, validation_error
from app.extensions import db
from app.models import AiGeneration, Card, Deck, utcnow

generate_bp = Blueprint("generate", __name__)

BODY_MAX = 6 * 1024 * 1024        # this route only; every other route keeps MAX_CONTENT_LENGTH
FILE_MAX = 4 * 1024 * 1024        # decoded bytes
TEXT_FILE_MAX = 100_000           # characters, after decoding
PROMPT_MAX = 2000
FOCUS_MAX = 500
FILE_NAME_MAX = 255
SUGGEST_MIN_CARDS = 10
SUGGEST_CONTEXT = 200             # newest cards sent to the model in suggest mode
CAP_WINDOW = timedelta(hours=24)  # both caps are rolling (rule 5)

MODES = ("prompt", "file", "suggest")
PDF = "application/pdf"
FILE_TYPES = (PDF, "text/plain", "text/markdown")

UNSUPPORTED_FILE = "Only PDF, TXT and MD files are supported. Save other documents as a PDF first."
SITE_CAP = "AI generation has hit today's limit for the whole site. Try again later."


def _own_deck_or_404(deck_id: int) -> Deck:
    deck = Deck.query.filter_by(id=deck_id, user_id=current_user.id).first()
    if deck is None:
        raise not_found("Deck not found")
    return deck


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


def _valid_prompt(body: dict) -> str:
    prompt = body.get("prompt")
    prompt = prompt.strip() if isinstance(prompt, str) else ""
    if not prompt:
        raise validation_error("prompt is required.", "prompt")
    if len(prompt) > PROMPT_MAX:
        raise validation_error(f"prompt must be at most {PROMPT_MAX} characters.", "prompt")
    return prompt


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


def _valid_focus(body: dict) -> str | None:
    focus = body.get("focus")
    if focus is None:
        return None
    if not isinstance(focus, str):
        raise validation_error("focus must be text.", "focus")
    focus = focus.strip()
    if len(focus) > FOCUS_MAX:
        raise validation_error(f"focus must be at most {FOCUS_MAX} characters.", "focus")
    return focus or None


def _check_daily_caps() -> None:
    """The learner's cap, then the site's. Best effort: only saved generations count (A19)."""
    since = utcnow() - CAP_WINDOW
    recent = select(func.count()).select_from(AiGeneration).where(AiGeneration.created_at > since)

    limit = current_app.config["AI_DAILY_LIMIT"]
    if db.session.scalar(recent.where(AiGeneration.user_id == current_user.id)) >= limit:
        raise ApiError(
            429, f"You've reached the limit of {limit} AI generations in 24 hours. Try again later."
        )
    if db.session.scalar(recent) >= current_app.config["AI_SITE_DAILY_LIMIT"]:
        raise ApiError(429, SITE_CAP)


def _log(mode: str, count: int, kept: int, model: str, started: float, outcome: str) -> None:
    """One line per request (rule 17): never the prompt, the file, the cards or an error's text."""
    current_app.logger.info(
        "ai_generation mode=%s count=%d kept=%d model=%s ms=%d outcome=%s",
        mode, count, kept, model, (time.monotonic() - started) * 1000, outcome,
    )


@generate_bp.post("/decks/<int:deck_id>/generate")
@login_required
def generate(deck_id):
    # Before anything reads the body. Flask 3.1 lets one route raise its own limit.
    request.max_content_length = BODY_MAX

    deck = _own_deck_or_404(deck_id)
    body = json_object()

    mode = _valid_mode(body)
    count = _valid_count(body)
    prompt = file_name = file_text = attachment = focus = None
    if mode == "prompt":
        prompt = _valid_prompt(body)
    elif mode == "file":
        file_name, file_text, attachment = _valid_file(body)
        focus = _valid_focus(body)
    elif mode == "suggest" and deck.card_count < SUGGEST_MIN_CARDS:
        raise validation_error(
            "Suggest more content needs at least 10 cards in the deck.", "mode"
        )

    _check_daily_caps()

    existing_fronts = db.session.scalars(select(Card.front).where(Card.deck_id == deck.id)).all()
    existing = ()
    if mode == "suggest":
        rows = db.session.execute(
            select(Card.front, Card.back)
            .where(Card.deck_id == deck.id)
            .order_by(Card.id.desc())
            .limit(SUGGEST_CONTEXT)
        ).all()
        existing = [CardDraft(front=front, back=back) for front, back in rows]

    started = time.monotonic()
    model = "-"
    try:
        provider = get_provider()
        model = provider.name
        raw = provider.generate_cards(
            build_prompt(
                mode,
                count=count,
                deck_name=deck.name,
                deck_description=deck.description,
                prompt=prompt,
                file_text=file_text,
                attachment=attachment,
                focus=focus,
                existing=existing,
            )
        )
        drafts = clean_drafts(raw, count, existing_fronts)
    except AIRateLimited as e:
        _log(mode, count, 0, model, started, "rate_limited")
        raise ApiError(429, e.message) from None
    except AIUnavailable as e:
        _log(mode, count, 0, model, started, "unavailable")
        raise ApiError(503, e.message) from None

    generation = AiGeneration(
        user_id=current_user.id,
        deck_id=deck.id,
        mode=mode,
        requested_count=count,
        prompt=prompt or focus,
        source_filename=file_name,
        model=model,
        candidates=[{"front": d.front, "back": d.back, "status": "pending"} for d in drafts],
    )
    db.session.add(generation)
    db.session.commit()
    _log(mode, count, len(drafts), model, started, "ok")
    return jsonify(generation.to_dict()), 201
