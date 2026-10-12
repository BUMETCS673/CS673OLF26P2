"""Models live in one module each; import them from here.

    from app.models import AiGeneration, Card, Deck, User
"""

# Iteration 3, Step 0a: exporting AiGeneration.
# AI Utilization: ~100% of that change
# AI Tools Used: Claude Code (Claude Opus 5.5)
# AI-Assisted Activities:
#   Data model development
# Human role: plan approval, code review, and hands-on testing by Miles Cameron.

from app.models.ai_generation import AiGeneration
from app.models.base import TimestampMixin, as_utc, iso, utcnow
from app.models.card import Card
from app.models.deck import Deck
from app.models.user import User

__all__ = [
    "AiGeneration", "Card", "Deck", "TimestampMixin", "User", "as_utc", "iso", "utcnow",
]
