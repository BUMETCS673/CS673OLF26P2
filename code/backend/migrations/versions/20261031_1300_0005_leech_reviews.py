"""leech reviews: the leech_reviews table, and leech_next_at on cards

The server default on `leech_next_at` flags every existing card at the normal threshold, so cards
already at 4 or more lapses are picked up on the learner's next page load.

Revision ID: 0005_leech_reviews
Revises: 0004_ai_pipeline
Create Date: 2026-10-31 13:00:00.000000

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0005_leech_reviews"
down_revision = "0004_ai_pipeline"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "leech_reviews",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("thread_id", sa.String(length=36), nullable=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("deck_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("card_ids", sa.JSON(), nullable=True),
        sa.Column("model", sa.String(length=64), nullable=True),
        sa.Column("model_calls", sa.Integer(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("judge_model", sa.String(length=64), nullable=True),
        sa.Column("judge_input_tokens", sa.Integer(), nullable=False),
        sa.Column("judge_output_tokens", sa.Integer(), nullable=False),
        sa.Column("verification", sa.String(length=16), nullable=True),
        sa.Column("shared_cause", sa.Text(), nullable=True),
        sa.Column("recommendations", sa.JSON(), nullable=False),
        sa.Column("decisions", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["deck_id"], ["decks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("thread_id"),
    )
    op.create_index(op.f("ix_leech_reviews_deck_id"), "leech_reviews", ["deck_id"])
    op.create_index(op.f("ix_leech_reviews_user_id"), "leech_reviews", ["user_id"])
    op.add_column(
        "cards", sa.Column("leech_next_at", sa.Integer(), server_default="4", nullable=False)
    )


def downgrade():
    op.drop_column("cards", "leech_next_at")
    op.drop_index(op.f("ix_leech_reviews_user_id"), table_name="leech_reviews")
    op.drop_index(op.f("ix_leech_reviews_deck_id"), table_name="leech_reviews")
    op.drop_table("leech_reviews")
