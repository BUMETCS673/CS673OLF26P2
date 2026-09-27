"""card scheduling: state, due_at, interval_days, ease_factor, step, lapses

The six fields Anki keeps on a card, which the Lab 3 study stories schedule with (Step 0a
in code/plans/LAB_3_PLAN.md). Every NOT NULL column has a server default, and that is
what fills in the cards that already exist: they all become `new`, which is what they
are, with an ease of 2500 (250%).

Written by hand, like 0001, and verified by the Migrations job in CI: `flask db upgrade`
against an empty Postgres, then `flask db check` against the models, then a round trip
through `downgrade base`.

Revision ID: 0002_card_scheduling
Revises: 0001_initial_schema
Create Date: 2026-09-26 22:26:00.000000

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0002_card_scheduling"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None


def upgrade():
    # batch_alter_table so the same file also applies to SQLite, which can't alter a
    # table in place (see render_as_batch in app/__init__.py). On Postgres it's a plain
    # ALTER TABLE.
    with op.batch_alter_table("cards") as batch_op:
        batch_op.add_column(
            sa.Column("state", sa.String(length=16), nullable=False, server_default="new")
        )
        batch_op.add_column(sa.Column("due_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(
            sa.Column("interval_days", sa.Integer(), nullable=False, server_default="0")
        )
        batch_op.add_column(
            sa.Column("ease_factor", sa.Integer(), nullable=False, server_default="2500")
        )
        batch_op.add_column(sa.Column("step", sa.Integer(), nullable=False, server_default="0"))
        batch_op.add_column(sa.Column("lapses", sa.Integer(), nullable=False, server_default="0"))


def downgrade():
    with op.batch_alter_table("cards") as batch_op:
        batch_op.drop_column("lapses")
        batch_op.drop_column("step")
        batch_op.drop_column("ease_factor")
        batch_op.drop_column("interval_days")
        batch_op.drop_column("due_at")
        batch_op.drop_column("state")
