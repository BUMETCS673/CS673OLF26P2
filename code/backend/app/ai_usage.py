"""Model calls counted toward the site's daily cap, across every AI feature."""

from datetime import timedelta

from sqlalchemy import func, select

from app.extensions import db
from app.models import AiGeneration, LeechReview, utcnow

CAP_WINDOW = timedelta(hours=24)  # both caps are rolling (rule 5)


def site_model_calls() -> int:
    """All saved model calls in the cap window, including empty batches."""
    since = utcnow() - CAP_WINDOW
    return sum(
        db.session.scalar(
            select(func.coalesce(func.sum(model.model_calls), 0)).where(model.created_at > since)
        )
        for model in (AiGeneration, LeechReview)
    )
