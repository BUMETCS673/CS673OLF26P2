"""An uploaded study file. Only its owner can select it, but its chunks join the knowledge base."""

from sqlalchemy import ForeignKey, LargeBinary, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin

PROCESSING = "processing"
READY = "ready"
FAILED = "failed"

# Where a PROCESSING document is, for the upload screen's progress.
QUEUED = "queued"
READING = "reading"
EMBEDDING = "embedding"
SCREENING = "screening"
FINDING_TOPICS = "finding_topics"


class Document(TimestampMixin, Base):
    __tablename__ = "documents"
    # Uploading the same file again reuses this row. It also covers lookups by user_id.
    __table_args__ = (UniqueConstraint("user_id", "content_hash"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    filename: Mapped[str] = mapped_column(String(255))
    content_hash: Mapped[str] = mapped_column(String(64))  # SHA-256, in hex
    mime_type: Mapped[str] = mapped_column(String(64))
    size_bytes: Mapped[int]
    job_id: Mapped[int | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"))
    status: Mapped[str] = mapped_column(String(16), default=PROCESSING)
    stage: Mapped[str] = mapped_column(String(16), default=QUEUED)
    chunks_total: Mapped[int] = mapped_column(default=0)
    chunks_done: Mapped[int] = mapped_column(default=0)
    suggested_topics: Mapped[list[str] | None] = mapped_column(JSONB)
    embedding_model: Mapped[str | None] = mapped_column(String(64))
    error: Mapped[str | None] = mapped_column(String(255))


class DocumentFilePart(Base):
    """One piece of an uploaded file, so a large file can be read without loading all of it."""

    __tablename__ = "document_file_parts"

    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), primary_key=True
    )
    number: Mapped[int] = mapped_column(primary_key=True)
    data: Mapped[bytes] = mapped_column(LargeBinary)
