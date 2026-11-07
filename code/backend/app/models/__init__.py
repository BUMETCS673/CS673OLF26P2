"""Every table, so importing this registers them all on `Base.metadata`."""

from app.models.ai_generation import AiGeneration
from app.models.ai_usage import AiUsage
from app.models.api_token import ApiToken
from app.models.base import Base, TimestampMixin, utcnow
from app.models.card import Card
from app.models.card_report import CardReport, ChunkReport
from app.models.deck import Deck
from app.models.document import Document, DocumentFilePart
from app.models.job import Job
from app.models.knowledge_chunk import KnowledgeChunk
from app.models.oauth_client import OAuthClient
from app.models.oauth_token import OAuthToken
from app.models.problem_card_review import ProblemCardReview
from app.models.tutor import TutorConversation
from app.models.user import User, normalize_email
from app.models.user_session import UserSession

__all__ = [
    "AiGeneration", "AiUsage", "ApiToken", "Base", "Card", "CardReport", "ChunkReport", "Deck",
    "Document", "DocumentFilePart",
    "Job", "KnowledgeChunk", "OAuthClient", "OAuthToken", "ProblemCardReview", "TimestampMixin",
    "TutorConversation", "User", "UserSession",
    "normalize_email", "utcnow",
]
