"""ai generation: the ai_generations table, and origin and generation_id on cards

What Iteration 3's AI card generation stores (Step 0a in code/plans/ITERATION_3_PLAN.md):
each batch of suggestions waits in ai_generations until the learner accepts or rejects
it, and every card records whether a person or the AI wrote it. The server default on
`origin` is what makes every card that already exists "manual".

Written by hand, like 0001 and 0002, and verified by the Migrations job in CI: `flask db
upgrade` against an empty Postgres, then `flask db check` against the models, then a
round trip through `downgrade base`.

Revision ID: 0003_ai_generation
Revises: 0002_card_scheduling
Create Date: 2026-10-08 19:04:00.000000

"""

# AI Utilization: ~100% of this file's code
# AI Tools Used: Claude Code (Claude Opus 5.5)
# AI-Assisted Activities:
#   Database migration
# Human role: plan approval, code review, and hands-on testing by Miles Cameron.

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0003_ai_generation"
down_revision = "0002_card_scheduling"
branch_labels = None
depends_on = None


def upgrade():
    # The table first: the new foreign key on cards points at it.
    op.create_table(
        "ai_generations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("deck_id", sa.Integer(), nullable=False),
        sa.Column("mode", sa.String(length=16), nullable=False),
        sa.Column("prompt", sa.String(length=2000), nullable=True),
        sa.Column("source_filename", sa.String(length=255), nullable=True),
        sa.Column("requested_count", sa.Integer(), nullable=False),
        sa.Column("model", sa.String(length=64), nullable=False),
        sa.Column("candidates", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        # Deleting a user or a deck removes its generations in the database, the same way
        # it removes cards; there's no relationship for SQLAlchemy to do it with.
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["deck_id"], ["decks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_ai_generations_user_id"), "ai_generations", ["user_id"], unique=False
    )
    op.create_index(
        op.f("ix_ai_generations_deck_id"), "ai_generations", ["deck_id"], unique=False
    )

    # batch_alter_table so the same file also applies to SQLite, which can't alter a
    # table in place (see render_as_batch in app/__init__.py). On Postgres it's a plain
    # ALTER TABLE.
    with op.batch_alter_table("cards") as batch_op:
        batch_op.add_column(
            sa.Column("origin", sa.String(length=16), nullable=False, server_default="manual")
        )
        batch_op.add_column(sa.Column("generation_id", sa.Integer(), nullable=True))
        # Named, because SQLite's batch mode can't create an unnamed one. The name matches
        # the model's, or `flask db check` reports a difference.
        batch_op.create_foreign_key(
            "fk_cards_generation_id_ai_generations",
            "ai_generations",
            ["generation_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade():
    # The reverse order: the foreign key, the columns, the indexes, then the table.
    with op.batch_alter_table("cards") as batch_op:
        batch_op.drop_constraint("fk_cards_generation_id_ai_generations", type_="foreignkey")
        batch_op.drop_column("generation_id")
        batch_op.drop_column("origin")

    op.drop_index(op.f("ix_ai_generations_deck_id"), table_name="ai_generations")
    op.drop_index(op.f("ix_ai_generations_user_id"), table_name="ai_generations")
    op.drop_table("ai_generations")
