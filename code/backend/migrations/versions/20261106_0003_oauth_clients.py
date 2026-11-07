"""oauth clients

Revision ID: 0003_oauth_clients
Revises: 0002_api_tokens
Create Date: 2026-11-06 00:00:00.000000

"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0003_oauth_clients"
down_revision = "0002_api_tokens"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "oauth_clients",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("client_id", sa.String(64), nullable=False),
        sa.Column("client_info", JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("client_id", name="uq_oauth_clients_client_id"),
    )


def downgrade() -> None:
    op.drop_table("oauth_clients")
