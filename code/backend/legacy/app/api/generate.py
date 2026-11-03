"""Generating cards with AI - B3 (Duc).

The blueprint is registered by `app/api/__init__.py`. Like `cards_bp`, it has no
url_prefix:

    POST /api/decks/<deck_id>/generate
         {mode: "prompt", count, prompt}
         {mode: "file", count, document_id, topic}
      -> 201 Generation    404, 400, 422 + field, 429 rate_limited, 503 ai_unavailable

    POST /api/decks/<deck_id>/suggestions
      -> 200 {topics}      404, 429 rate_limited, 503 ai_unavailable

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

from flask import Blueprint, current_app, jsonify
from flask_login import current_user, login_required

from app.api.decks import own_deck_or_404
from app.api.validation import required_text
from app.errors import json_object, not_found, validation_error
from app.models import Document
from app.models.document import READY
from app.services.generation import GenerationRequest, generate_cards, suggest_topics_for_deck

generate_bp = Blueprint("generate", __name__)

PROMPT_MAX = 2000
TOPIC_MAX = 500

MODES = ("prompt", "file")


def _valid_mode(body: dict) -> str:
    mode = body.get("mode")
    if mode not in MODES:
        raise validation_error("mode must be one of: prompt, file.", "mode")
    return mode


def _valid_count(body: dict) -> int:
    count = body.get("count")
    limit = current_app.config["AI_MAX_CARDS"]
    # `type() is int`, not isinstance: True is an int to Python, and the contract refuses it.
    if type(count) is not int or not 1 <= count <= limit:
        raise validation_error(f"count must be a whole number from 1 to {limit}.", "count")
    return count


def _valid_document(body: dict) -> Document:
    """The signed-in user's saved document, once it's ready to search."""
    document_id = body.get("document_id")
    if type(document_id) is not int:
        raise validation_error("document_id must be a whole number.", "document_id")
    document = Document.query.filter_by(id=document_id, user_id=current_user.id).first()
    if document is None:
        raise not_found("Document not found")
    if document.status != READY:
        raise validation_error("That file isn't ready yet.", "document_id")
    return document


@generate_bp.post("/decks/<int:deck_id>/suggestions")
@login_required
def suggestions(deck_id):
    deck = own_deck_or_404(deck_id)
    return jsonify({"topics": suggest_topics_for_deck(deck, current_user.id)})


@generate_bp.post("/decks/<int:deck_id>/generate")
@login_required
def generate(deck_id):
    deck = own_deck_or_404(deck_id)
    body = json_object()

    mode = _valid_mode(body)
    count = _valid_count(body)
    prompt = file_name = focus = document_id = None
    if mode == "prompt":
        prompt = required_text(body.get("prompt"), "prompt", PROMPT_MAX)
    else:
        document = _valid_document(body)
        file_name, document_id = document.filename, document.id
        focus = required_text(body.get("topic"), "topic", TOPIC_MAX)

    generation = generate_cards(deck, current_user.id, GenerationRequest(
        mode=mode,
        count=count,
        prompt=prompt,
        file_name=file_name,
        focus=focus,
        document_id=document_id,
    ))
    return jsonify(generation.to_dict()), 201
