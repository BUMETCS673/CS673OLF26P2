"""deck tutor and usage: tutor_conversations and ai_usage, replacing per-feature spending columns

Every AI call is now recorded in ai_usage. Existing rows aren't copied over, so the rolling budgets
start empty, which is harmless because they only look back 24 hours.

Revision ID: 0006_deck_tutor
Revises: 0005_leech_reviews
Create Date: 2026-10-31 14:00:00.000000

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0006_deck_tutor"
down_revision = "0005_leech_reviews"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "tutor_conversations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("deck_id", sa.Integer(), nullable=False),
        sa.Column("thread_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("status_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("pending_proposal", sa.JSON(), nullable=True),
        sa.Column("message_count", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["deck_id"], ["decks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("deck_id"),
        sa.UniqueConstraint("thread_id"),
    )
    op.create_index(op.f("ix_tutor_conversations_user_id"), "tutor_conversations", ["user_id"])

    op.create_table(
        "ai_usage",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("feature", sa.String(length=16), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("model", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("deck_id", sa.Integer(), nullable=True),
        sa.Column("prompt_version", sa.String(length=16), nullable=True),
        sa.Column("calls", sa.Integer(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["deck_id"], ["decks.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_ai_usage_created_at"), "ai_usage", ["created_at"])
    op.create_index(op.f("ix_ai_usage_user_id"), "ai_usage", ["user_id"])

    # The per-user generation cap still filters on this.
    op.create_index(op.f("ix_ai_generations_created_at"), "ai_generations", ["created_at"])

    for column in (
        "model_calls", "input_tokens", "output_tokens", "judge_model", "judge_input_tokens",
        "judge_output_tokens",
    ):
        op.drop_column("ai_generations", column)
    for column in (
        "model", "model_calls", "input_tokens", "output_tokens", "judge_model",
        "judge_input_tokens", "judge_output_tokens",
    ):
        op.drop_column("leech_reviews", column)


def downgrade():
    # Server defaults fill existing rows. The spending they recorded isn't restored.
    for column, kind in (
        ("model", sa.String(length=64)), ("judge_model", sa.String(length=64)),
    ):
        op.add_column("leech_reviews", sa.Column(column, kind, nullable=True))
    for column in (
        "model_calls", "input_tokens", "output_tokens", "judge_input_tokens",
        "judge_output_tokens",
    ):
        op.add_column(
            "leech_reviews", sa.Column(column, sa.Integer(), server_default="0", nullable=False)
        )

    op.add_column(
        "ai_generations", sa.Column("model_calls", sa.Integer(), server_default="1", nullable=False)
    )
    op.add_column("ai_generations", sa.Column("judge_model", sa.String(length=64), nullable=True))
    for column in (
        "input_tokens", "output_tokens", "judge_input_tokens", "judge_output_tokens",
    ):
        op.add_column("ai_generations", sa.Column(column, sa.Integer(), nullable=True))

    op.drop_index(op.f("ix_ai_generations_created_at"), table_name="ai_generations")
    op.drop_index(op.f("ix_ai_usage_user_id"), table_name="ai_usage")
    op.drop_index(op.f("ix_ai_usage_created_at"), table_name="ai_usage")
    op.drop_table("ai_usage")
    op.drop_index(op.f("ix_tutor_conversations_user_id"), table_name="tutor_conversations")
    op.drop_table("tutor_conversations")
