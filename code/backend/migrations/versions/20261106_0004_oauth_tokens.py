"""oauth tokens

Revision ID: 0004_oauth_tokens
Revises: 0003_oauth_clients
Create Date: 2026-11-06 00:00:00.000000

"""

import sqlalchemy as sa
from alembic import op

revision = "0004_oauth_tokens"
down_revision = "0003_oauth_clients"
branch_labels = None
depends_on = None

TIMESTAMP = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "oauth_tokens",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("client_id", sa.String(64), nullable=False),
        sa.Column("access_hash", sa.String(64), nullable=False),
        sa.Column("refresh_hash", sa.String(64), nullable=False),
        sa.Column("scope", sa.String(1000), nullable=False),
        sa.Column("resource", sa.String(500)),
        sa.Column("access_expires_at", TIMESTAMP, nullable=False),
        sa.Column("refresh_expires_at", TIMESTAMP, nullable=False),
        sa.Column("created_at", TIMESTAMP, nullable=False),
        sa.Column("last_used_at", TIMESTAMP),
        sa.Column("revoked_at", TIMESTAMP),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_oauth_tokens_user_id_users", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["client_id"],
            ["oauth_clients.client_id"],
            name="fk_oauth_tokens_client_id_oauth_clients",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("access_hash", name="uq_oauth_tokens_access_hash"),
        sa.UniqueConstraint("refresh_hash", name="uq_oauth_tokens_refresh_hash"),
    )
    op.create_index("ix_oauth_tokens_user_id", "oauth_tokens", ["user_id"])
    op.create_index("ix_oauth_tokens_client_id", "oauth_tokens", ["client_id"])


def downgrade() -> None:
    op.drop_table("oauth_tokens")
