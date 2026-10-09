"""The `/api` blueprint, and the feature blueprints hanging off it.

WS0 wired up the first three against modules that had no routes in them yet, so WS1 and
WS2 each only ever touched their own file. **Nobody edits this file again** — if you
find yourself needing to, say so in the team channel first (see "Shared files" in
code/plans/ITERATION_1_PLAN.md).

Iteration 3's Step 0a is the agreed exception: it registers the two AI blueprints the
same way, so B3 and B4 only ever touch their own files (see "File ownership" in
code/plans/ITERATION_3_PLAN.md).
"""

# Iteration 3, Step 0a: registering generate_bp and generations_bp.
# AI Utilization: ~100% of that change
# AI Tools Used: Claude Code (Claude Opus 5.5)
# AI-Assisted Activities:
#   Blueprint registration
# Human role: plan approval, code review, and hands-on testing by Miles Cameron.

from flask import Blueprint, jsonify

from app.api.auth import auth_bp
from app.api.cards import cards_bp
from app.api.decks import decks_bp
from app.api.generate import generate_bp
from app.api.generations import generations_bp

api_bp = Blueprint("api", __name__)


@api_bp.get("/health")
def health():
    """Liveness check. `curl localhost:5001/api/health` should say ok."""
    return jsonify({"status": "ok"}), 200


api_bp.register_blueprint(auth_bp)         # WS1 — /api/auth/...
api_bp.register_blueprint(decks_bp)        # WS2 — /api/decks...
api_bp.register_blueprint(cards_bp)        # WS2 — /api/decks/<id>/cards, /api/cards/<id>
api_bp.register_blueprint(generate_bp)     # B3 — /api/decks/<id>/generate
api_bp.register_blueprint(generations_bp)  # B4 — /api/generations/<id>/accept, /reject
