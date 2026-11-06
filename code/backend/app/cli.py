"""Demo and admin commands, never HTTP routes. Run them with `python -m app.cli --help`."""

import asyncio
from typing import Annotated

import typer

from app.ai.models import AIRateLimited, AIUnavailable, Role, load_embeddings, model_name
from app.core.database import get_engine, get_session_factory
from app.core.errors import NotFound
from app.core.redis import get_redis
from app.core.settings import get_settings
from app.models import utcnow
from app.repositories.unit_of_work import open_unit_of_work
from app.services.demo import DEMO_EMAIL, DEMO_PASSWORD, DemoService
from app.services.reindex import reindex

cli = typer.Typer(no_args_is_help=True)


async def _with_service(work):
    """Run `work(service)` in one session, then close the database connections."""
    try:
        async with open_unit_of_work(get_session_factory()) as tx:
            return await work(DemoService(tx.session, tx.users, tx.decks, tx.cards))
    finally:
        await get_engine().dispose()


@cli.command()
def seed(
    reset: Annotated[bool, typer.Option(help="Delete the demo user first.")] = False,
) -> None:
    """Insert the demo user and their two decks."""
    decks = asyncio.run(_with_service(lambda service: service.seed(reset=reset)))
    if decks is None:
        typer.echo(f"{DEMO_EMAIL} already exists, so nothing changed. Use --reset to start over.")
        return
    summary = " and ".join(f"{d.name!r} (id {d.id}, {d.card_count} cards)" for d in decks)
    typer.echo(f"Seeded {DEMO_EMAIL} (password: {DEMO_PASSWORD}) with {summary}.")


@cli.command()
def time_travel(
    days: Annotated[int, typer.Option(min=1, help="How many days to pretend have passed.")],
    email: Annotated[str, typer.Option(help="Whose cards to move.")] = DEMO_EMAIL,
) -> None:
    """Make days pass for one user: every due time moves earlier, and new cards don't change."""
    try:
        found, moved = asyncio.run(_with_service(lambda service: service.time_travel(days, email)))
    except NotFound as error:
        typer.echo(error.message, err=True)
        raise typer.Exit(1) from None
    typer.echo(f"Moved {moved} of {found}'s cards {days} day(s) earlier.")


async def _hide(work) -> int:
    try:
        async with open_unit_of_work(get_session_factory()) as tx:
            hidden = await work(tx.knowledge)
            await tx.commit()
            return hidden
    finally:
        await get_engine().dispose()


@cli.command()
def hide_document(document_id: int) -> None:
    """Take one uploaded file out of shared search for good."""
    hidden = asyncio.run(_hide(lambda knowledge: knowledge.hide_document(document_id)))
    typer.echo(f"Hid {hidden} chunks.")


@cli.command()
def hide_user(user_id: int) -> None:
    """Take everything one learner uploaded or first accepted out of shared search for good."""
    hidden = asyncio.run(_hide(lambda knowledge: knowledge.hide_user(user_id)))
    typer.echo(f"Hid {hidden} chunks.")


@cli.command()
def unhide_document(document_id: int) -> None:
    """Undo a wrong hide of one uploaded file, including hides from reports."""
    restored = asyncio.run(_hide(lambda knowledge: knowledge.unhide_document(document_id)))
    typer.echo(f"Restored {restored} chunks.")


@cli.command()
def unhide_user(user_id: int) -> None:
    """Undo a wrong hide of what one learner uploaded or first accepted, and restore trust."""
    restored = asyncio.run(_unhide_user(user_id))
    typer.echo(f"Restored {restored} chunks.")


async def _unhide_user(user_id: int) -> int:
    try:
        async with open_unit_of_work(get_session_factory()) as tx:
            restored = await tx.knowledge.unhide_user(user_id)
            if await tx.users.restore_trust(user_id, utcnow()):
                await tx.knowledge.share_waiting_chunks(user_id)
            await tx.commit()
            return restored
    finally:
        await get_engine().dispose()


async def _reindex() -> int:
    try:
        settings = get_settings()
        return await reindex(
            get_session_factory(), load_embeddings(settings), model_name(Role.EMBEDDER, settings)
        )
    finally:
        await get_redis().aclose()
        await get_engine().dispose()


@cli.command("reindex")
def reindex_command() -> None:
    """Embed chunks and cards with the current model, as needed after changing it. Safe to rerun."""
    try:
        embedded = asyncio.run(_reindex())
    except (AIRateLimited, AIUnavailable) as error:
        typer.echo(f"{error.message} Run it again to continue from where it stopped.", err=True)
        raise typer.Exit(1) from None
    typer.echo(f"Embedded {embedded} chunks and cards.")


if __name__ == "__main__":
    cli()
