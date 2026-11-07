"""api tokens

Revision ID: 0002_api_tokens
Revises: 0001_initial_schema
Create Date: 2026-11-06 00:00:00.000000

"""

import sqlalchemy as sa
from alembic import op

revision = "0002_api_tokens"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None

TIMESTAMP = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "api_tokens",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("created_at", TIMESTAMP, nullable=False),
        sa.Column("last_used_at", TIMESTAMP),
        sa.Column("revoked_at", TIMESTAMP),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_api_tokens_user_id_users", ondelete="CASCADE"
        ),
        sa.UniqueConstraint("token_hash", name="uq_api_tokens_token_hash"),
    )
    op.create_index("ix_api_tokens_user_id", "api_tokens", ["user_id"])


def downgrade() -> None:
    op.drop_table("api_tokens")
