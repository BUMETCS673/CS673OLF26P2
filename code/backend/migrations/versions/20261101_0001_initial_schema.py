"""initial schema

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-11-01 00:00:00.000000

"""

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR

revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None

TIMESTAMP = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("display_name", sa.String(120)),
        sa.Column("created_at", TIMESTAMP, nullable=False),
        sa.Column("trusted_at", TIMESTAMP),
        sa.Column("trust_lost_at", TIMESTAMP),
        sa.UniqueConstraint("email", name="uq_users_email"),
    )

    op.create_table(
        "user_sessions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("expires_at", TIMESTAMP, nullable=False),
        sa.Column("created_at", TIMESTAMP, nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_user_sessions_user_id_users", ondelete="CASCADE"
        ),
        sa.UniqueConstraint("token_hash", name="uq_user_sessions_token_hash"),
    )
    op.create_index("ix_user_sessions_user_id", "user_sessions", ["user_id"])

    op.create_table(
        "decks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("description", sa.String(1000)),
        sa.Column("created_at", TIMESTAMP, nullable=False),
        sa.Column("updated_at", TIMESTAMP, nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_decks_user_id_users", ondelete="CASCADE"
        ),
    )
    op.create_index("ix_decks_user_id", "decks", ["user_id"])

    op.create_table(
        "jobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("payload", JSONB(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("enqueued_at", TIMESTAMP),
        sa.Column("lease_until", TIMESTAMP),
        sa.Column("retry_at", TIMESTAMP),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("result", JSONB()),
        sa.Column("error", sa.String(255)),
        sa.Column("created_at", TIMESTAMP, nullable=False),
        sa.Column("updated_at", TIMESTAMP, nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_jobs_user_id_users", ondelete="CASCADE"
        ),
    )
    op.create_index("ix_jobs_user_id", "jobs", ["user_id"])
    op.create_index(
        "ix_jobs_unfinished",
        "jobs",
        ["status", "enqueued_at"],
        postgresql_where=sa.text("status IN ('queued', 'running')"),
    )

    op.create_table(
        "ai_generations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("job_id", sa.Integer()),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("deck_id", sa.Integer(), nullable=False),
        sa.Column("mode", sa.String(16), nullable=False),
        sa.Column("prompt", sa.String(2000)),
        sa.Column("source_filename", sa.String(255)),
        sa.Column("requested_count", sa.Integer(), nullable=False),
        sa.Column("model", sa.String(64), nullable=False),
        sa.Column("verification", sa.String(16)),
        sa.Column("empty", sa.Boolean(), nullable=False),
        sa.Column("prompt_version", sa.String(16)),
        sa.Column("candidates", JSONB(), nullable=False),
        sa.Column("source_chunk_ids", JSONB(), nullable=False),
        sa.Column("created_at", TIMESTAMP, nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_ai_generations_user_id_users", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["deck_id"], ["decks.id"], name="fk_ai_generations_deck_id_decks", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["job_id"], ["jobs.id"], name="fk_ai_generations_job_id_jobs", ondelete="SET NULL"
        ),
        sa.UniqueConstraint("job_id", name="uq_ai_generations_job_id"),
    )
    op.create_index("ix_ai_generations_user_id", "ai_generations", ["user_id"])
    op.create_index("ix_ai_generations_deck_id", "ai_generations", ["deck_id"])
    op.create_index("ix_ai_generations_created_at", "ai_generations", ["created_at"])

    op.create_table(
        "cards",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("deck_id", sa.Integer(), nullable=False),
        sa.Column("front", sa.String(2000), nullable=False),
        sa.Column("back", sa.String(2000), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("due_at", TIMESTAMP),
        sa.Column("interval_days", sa.Integer(), nullable=False),
        sa.Column("ease_factor", sa.Integer(), nullable=False),
        sa.Column("step", sa.Integer(), nullable=False),
        sa.Column("lapses", sa.Integer(), nullable=False),
        sa.Column("last_reviewed_at", TIMESTAMP),
        sa.Column("origin", sa.String(16), nullable=False),
        sa.Column("generation_id", sa.Integer()),
        sa.Column("problem_at_lapses", sa.Integer(), nullable=False),
        sa.Column("embedding", Vector(768)),
        sa.Column("embedding_model", sa.String(64)),
        sa.Column("created_at", TIMESTAMP, nullable=False),
        sa.Column("updated_at", TIMESTAMP, nullable=False),
        sa.ForeignKeyConstraint(
            ["deck_id"], ["decks.id"], name="fk_cards_deck_id_decks", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["generation_id"],
            ["ai_generations.id"],
            name="fk_cards_generation_id_ai_generations",
            ondelete="SET NULL",
        ),
    )
    op.create_index("ix_cards_deck_id", "cards", ["deck_id"])

    op.create_table(
        "card_reports",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("card_id", sa.Integer(), nullable=False),
        sa.Column("created_at", TIMESTAMP, nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_card_reports_user_id_users", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["card_id"], ["cards.id"], name="fk_card_reports_card_id_cards", ondelete="CASCADE"
        ),
        sa.UniqueConstraint("user_id", "card_id", name="uq_card_reports_user_id_card_id"),
    )

    op.create_table(
        "ai_usage",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("feature", sa.String(16), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("model", sa.String(64), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("deck_id", sa.Integer()),
        sa.Column("prompt_version", sa.String(16)),
        sa.Column("calls", sa.Integer(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("created_at", TIMESTAMP, nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_ai_usage_user_id_users", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["deck_id"], ["decks.id"], name="fk_ai_usage_deck_id_decks", ondelete="SET NULL"
        ),
    )
    op.create_index(
        "ix_ai_usage_model_created_at",
        "ai_usage",
        ["model", "created_at"],
        postgresql_include=["calls"],
    )
    op.create_index(
        "ix_ai_usage_feature_created_at",
        "ai_usage",
        ["feature", "created_at"],
        postgresql_include=["calls", "user_id"],
    )
    op.create_index(
        "ix_ai_usage_user_id_feature_created_at",
        "ai_usage",
        ["user_id", "feature", "created_at"],
        postgresql_include=["calls"],
    )

    op.create_table(
        "problem_card_reviews",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("thread_id", sa.String(36)),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("deck_id", sa.Integer(), nullable=False),
        sa.Column("job_id", sa.Integer()),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("card_ids", JSONB()),
        sa.Column("verification", sa.String(16)),
        sa.Column("shared_cause", sa.Text()),
        sa.Column("recommendations", JSONB(), nullable=False),
        sa.Column("decisions", JSONB()),
        sa.Column("created_at", TIMESTAMP, nullable=False),
        sa.Column("completed_at", TIMESTAMP),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_problem_card_reviews_user_id_users",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["deck_id"],
            ["decks.id"],
            name="fk_problem_card_reviews_deck_id_decks",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("thread_id", name="uq_problem_card_reviews_thread_id"),
        sa.ForeignKeyConstraint(
            ["job_id"], ["jobs.id"], name="fk_problem_card_reviews_job_id_jobs", ondelete="SET NULL"
        ),
    )
    op.create_index("ix_problem_card_reviews_user_id", "problem_card_reviews", ["user_id"])
    op.create_index("ix_problem_card_reviews_deck_id", "problem_card_reviews", ["deck_id"])
    op.create_index(
        "uq_problem_card_reviews_one_active",
        "problem_card_reviews",
        ["deck_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('queued', 'pending')"),
    )

    op.create_table(
        "tutor_conversations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("deck_id", sa.Integer(), nullable=False),
        sa.Column("thread_id", sa.String(36), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("status_at", TIMESTAMP, nullable=False),
        sa.Column("pending_proposal", JSONB()),
        sa.Column("message_count", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_tutor_conversations_user_id_users",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["deck_id"],
            ["decks.id"],
            name="fk_tutor_conversations_deck_id_decks",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("deck_id", name="uq_tutor_conversations_deck_id"),
        sa.UniqueConstraint("thread_id", name="uq_tutor_conversations_thread_id"),
    )
    op.create_index("ix_tutor_conversations_user_id", "tutor_conversations", ["user_id"])

    op.create_table(
        "documents",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("mime_type", sa.String(64), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("job_id", sa.Integer()),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("stage", sa.String(16), nullable=False),
        sa.Column("chunks_total", sa.Integer(), nullable=False),
        sa.Column("chunks_done", sa.Integer(), nullable=False),
        sa.Column("suggested_topics", JSONB()),
        sa.Column("embedding_model", sa.String(64)),
        sa.Column("error", sa.String(255)),
        sa.Column("created_at", TIMESTAMP, nullable=False),
        sa.Column("updated_at", TIMESTAMP, nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_documents_user_id_users", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["job_id"], ["jobs.id"], name="fk_documents_job_id_jobs", ondelete="SET NULL"
        ),
        sa.UniqueConstraint("user_id", "content_hash", name="uq_documents_user_id_content_hash"),
    )

    op.create_table(
        "document_file_parts",
        sa.Column("document_id", sa.Integer(), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("data", sa.LargeBinary(), nullable=False),
        sa.PrimaryKeyConstraint("document_id", "number", name="pk_document_file_parts"),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name="fk_document_file_parts_document_id_documents",
            ondelete="CASCADE",
        ),
    )
    # PDFs are already compressed, so don't spend CPU trying again on every insert.
    op.execute("ALTER TABLE document_file_parts ALTER COLUMN data SET STORAGE EXTERNAL")

    op.create_table(
        "knowledge_chunks",
        sa.Column("langchain_id", sa.Uuid(), primary_key=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("embedding", Vector(768), nullable=False),
        sa.Column("content_tsv", TSVECTOR()),
        sa.Column("langchain_metadata", sa.JSON()),
        sa.Column("embedding_model", sa.String(64), nullable=False),
        sa.Column("owner_id", sa.Integer()),
        sa.Column("document_id", sa.Integer()),
        sa.Column("chunk_index", sa.Integer()),
        sa.Column("page", sa.Integer()),
        sa.Column("source_card_id", sa.Integer()),
        sa.Column("shared", sa.Boolean()),
        sa.Column("passed_screening", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("hidden", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("shared_before_hide", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("accepted_by", sa.Integer()),
        sa.ForeignKeyConstraint(
            ["accepted_by"],
            ["users.id"],
            name="fk_knowledge_chunks_accepted_by_users",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["users.id"],
            name="fk_knowledge_chunks_owner_id_users",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name="fk_knowledge_chunks_document_id_documents",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_card_id"],
            ["cards.id"],
            name="fk_knowledge_chunks_source_card_id_cards",
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint("source_card_id", name="uq_knowledge_chunks_source_card_id"),
    )
    op.create_index("ix_knowledge_chunks_owner_id", "knowledge_chunks", ["owner_id"])
    op.create_index("ix_knowledge_chunks_document_id", "knowledge_chunks", ["document_id"])
    op.create_index("ix_knowledge_chunks_accepted_by", "knowledge_chunks", ["accepted_by"])
    op.create_index(
        "ix_knowledge_chunks_embedding",
        "knowledge_chunks",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    op.create_index(
        "ix_knowledge_chunks_card_copy_embedding",
        "knowledge_chunks",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
        postgresql_where=sa.text("accepted_by IS NOT NULL"),
    )
    op.create_index(
        "ix_knowledge_chunks_content_tsv",
        "knowledge_chunks",
        ["content_tsv"],
        postgresql_using="gin",
    )

    op.create_table(
        "chunk_reports",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("reporter_id", sa.Integer(), nullable=False),
        sa.Column("target_user_id", sa.Integer(), nullable=False),
        sa.Column("chunk_id", sa.Uuid(), nullable=False),
        sa.Column("reporter_trusted", sa.Boolean(), nullable=False),
        sa.Column("created_at", TIMESTAMP, nullable=False),
        sa.ForeignKeyConstraint(
            ["reporter_id"],
            ["users.id"],
            name="fk_chunk_reports_reporter_id_users",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["target_user_id"],
            ["users.id"],
            name="fk_chunk_reports_target_user_id_users",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["chunk_id"],
            ["knowledge_chunks.langchain_id"],
            name="fk_chunk_reports_chunk_id_knowledge_chunks",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "reporter_id", "chunk_id", name="uq_chunk_reports_reporter_id_chunk_id"
        ),
    )
    op.create_index("ix_chunk_reports_target_user_id", "chunk_reports", ["target_user_id"])


def downgrade() -> None:
    for table in (
        "card_reports", "chunk_reports", "knowledge_chunks", "document_file_parts", "documents",
        "tutor_conversations",
        "problem_card_reviews", "ai_usage", "cards", "ai_generations", "jobs", "decks",
        "user_sessions", "users",
    ):
        op.drop_table(table)
    op.execute("DROP EXTENSION IF EXISTS vector")
