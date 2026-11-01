"""ai pipeline: spend, verification and prompt tracking on ai_generations

A batch can now spend more than one model call, so the site cap sums `model_calls`, and the
server default counts every existing row as the one call it was. Empty batches are excluded
from the per-user cap. Token counts and `prompt_version` stay null on existing rows.

Written by hand, like 0001 to 0003, and verified by the Migrations job in CI.

Revision ID: 0004_ai_pipeline
Revises: 0003_ai_generation
Create Date: 2026-10-31 12:00:00.000000

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0004_ai_pipeline"
down_revision = "0003_ai_generation"
branch_labels = None
depends_on = None


def upgrade():
    # Non-nullable columns need a server default so that existing rows can be filled in.
    op.add_column(
        "ai_generations",
        sa.Column("model_calls", sa.Integer(), server_default="1", nullable=False),
    )
    op.add_column("ai_generations", sa.Column("verification", sa.String(length=16), nullable=True))
    op.add_column(
        "ai_generations",
        sa.Column("empty", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.add_column(
        "ai_generations", sa.Column("prompt_version", sa.String(length=16), nullable=True)
    )
    op.add_column("ai_generations", sa.Column("input_tokens", sa.Integer(), nullable=True))
    op.add_column("ai_generations", sa.Column("output_tokens", sa.Integer(), nullable=True))
    op.add_column("ai_generations", sa.Column("judge_model", sa.String(length=64), nullable=True))
    op.add_column("ai_generations", sa.Column("judge_input_tokens", sa.Integer(), nullable=True))
    op.add_column("ai_generations", sa.Column("judge_output_tokens", sa.Integer(), nullable=True))


def downgrade():
    # Reverse order of upgrade().
    op.drop_column("ai_generations", "judge_output_tokens")
    op.drop_column("ai_generations", "judge_input_tokens")
    op.drop_column("ai_generations", "judge_model")
    op.drop_column("ai_generations", "output_tokens")
    op.drop_column("ai_generations", "input_tokens")
    op.drop_column("ai_generations", "prompt_version")
    op.drop_column("ai_generations", "empty")
    op.drop_column("ai_generations", "verification")
    op.drop_column("ai_generations", "model_calls")
