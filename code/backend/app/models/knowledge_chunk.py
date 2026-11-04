"""One searchable piece of the central knowledge base, from a document or an accepted card.

`PGVectorStore` reads and writes this table, so its column names and types must match what it
expects: `langchain_id`, `content`, `embedding`, `content_tsv` and `langchain_metadata`. The other
columns are metadata that searches can filter on.
"""

import uuid

from pgvector.sqlalchemy import Vector
from sqlalchemy import JSON, Boolean, ForeignKey, Index, String, Text, false, text
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

from app.core.settings import EMBEDDING_DIMENSIONS
from app.models.base import Base


class KnowledgeChunk(Base):
    __tablename__ = "knowledge_chunks"
    __table_args__ = (
        # Approximate nearest neighbours, so vector search stays fast as the table grows.
        Index(
            "ix_knowledge_chunks_embedding",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
        # Card copies only, for near-duplicate checks. They can be a small part of the table, where
        # walking the full index would pass many uploads before reaching one.
        Index(
            "ix_knowledge_chunks_card_copy_embedding",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
            postgresql_where=text("accepted_by IS NOT NULL"),
        ),
        # Keyword search, which hybrid search combines with vector search.
        Index("ix_knowledge_chunks_content_tsv", "content_tsv", postgresql_using="gin"),
    )

    langchain_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    content: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIMENSIONS))
    content_tsv: Mapped[str | None] = mapped_column(TSVECTOR)
    langchain_metadata: Mapped[dict | None] = mapped_column(JSON)

    embedding_model: Mapped[str] = mapped_column(String(64))  # vectors can't mix across models
    # Who uploaded it, for limiting how much one source can reach other users. Null for cards.
    owner_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    document_id: Mapped[int | None] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    chunk_index: Mapped[int | None]
    page: Mapped[int | None]  # null for TXT and MD files
    # A card's copy outlives the card, so this can be null too.
    source_card_id: Mapped[int | None] = mapped_column(
        ForeignKey("cards.id", ondelete="SET NULL"), unique=True
    )
    # True once it may reach other users' searches. The store writes null when it isn't given, so
    # a chunk stays private until screening passes it.
    shared: Mapped[bool | None] = mapped_column(Boolean)
    # An upload that screening cleared, waiting to be shared until its owner's account is trusted.
    passed_screening: Mapped[bool] = mapped_column(Boolean, server_default=false())
    # Reported or removed. Only the unhide commands can share it again.
    hidden: Mapped[bool] = mapped_column(Boolean, server_default=false())
    # Whether it was shared when hidden, so undoing a hide puts back exactly that.
    shared_before_hide: Mapped[bool] = mapped_column(Boolean, server_default=false())
    # For a card's copy, the first learner to accept it. A different learner confirms the fact.
    # Indexed, since hiding one learner's chunks filters on this or `owner_id`.
    accepted_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
