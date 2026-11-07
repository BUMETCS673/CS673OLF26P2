"""token expiry and client use

Revision ID: 0005_token_expiry_and_client_use
Revises: 0004_oauth_tokens
Create Date: 2026-11-06 00:00:00.000000

"""

import sqlalchemy as sa
from alembic import op

revision = "0005_token_expiry_and_client_use"
down_revision = "0004_oauth_tokens"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("api_tokens", sa.Column("expires_at", sa.DateTime(timezone=True)))
    op.add_column("oauth_clients", sa.Column("used_at", sa.DateTime(timezone=True)))


def downgrade() -> None:
    op.drop_column("oauth_clients", "used_at")
    op.drop_column("api_tokens", "expires_at")
