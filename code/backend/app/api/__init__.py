"""The `/api` blueprint, and the three feature blueprints hanging off it.

WS0 wires all three up front, against modules that have no routes in them yet, so WS1
and WS2 each only ever touch their own file. **Nobody edits this file again** — if you
find yourself needing to, say so in the team channel first (see "Shared files" in
ITERATION_1_PLAN.md).
"""

from flask import Blueprint, jsonify

from app.api.auth import auth_bp
from app.api.cards import cards_bp
from app.api.decks import decks_bp

api_bp = Blueprint("api", __name__)


@api_bp.get("/health")
def health():
    """Liveness check. `curl localhost:5001/api/health` should say ok."""
    return jsonify({"status": "ok"}), 200


api_bp.register_blueprint(auth_bp)   # WS1 — /api/auth/...
api_bp.register_blueprint(decks_bp)  # WS2 — /api/decks...
api_bp.register_blueprint(cards_bp)  # WS2 — /api/decks/<id>/cards, /api/cards/<id>
