"""`flask ai-smoke`: one real request to the configured AI provider (B2).

Asks for one card about the capital of France and prints it, with the provider's name
and how long it took:

    gemini-3.5-flash answered in 2.4 s: What is the capital of France? → Paris

Exits 1, with the message a learner would see, when the provider fails. On the stand-in
(AI_PROVIDER=fake) it prints a sample card and spends nothing. With AI_PROVIDER=gemini it
spends one of the free tier's requests for the day.

    docker compose exec backend flask ai-smoke
"""

# AI Utilization: ~100% of this file's code
# AI Tools Used: Claude Code (Claude Opus 5.5)
# AI-Assisted Activities:
#   CLI command development
#   Documentation
# Human role: plan approval, code review, and hands-on testing by Miles Cameron.

import time

import click
from flask.cli import with_appcontext

from app.ai.provider import AIRateLimited, AIUnavailable, Prompt, get_provider

# Written by hand rather than with build_prompt() (B1): this checks the provider, not the
# prompt, and it has to keep working whatever B1's rules say.
SMOKE_PROMPT = Prompt(
    system=(
        "You write flashcards. Return only JSON that matches the schema. The back is the "
        "bare answer, in 5 words or fewer."
    ),
    text="Write 1 flashcard about the capital of France.",
    max_cards=1,
)


@click.command("ai-smoke")
@with_appcontext
def ai_smoke_command():
    """Ask the configured AI provider for one card, and print it."""
    try:
        provider = get_provider()
        # A real model can take a while, and the wait is silent without this.
        click.echo(f"Asking {provider.name} for one card. This can take up to 45 seconds…")
        started = time.perf_counter()
        cards = provider.generate_cards(SMOKE_PROMPT)
    except (AIRateLimited, AIUnavailable) as error:
        click.echo(error.message, err=True)
        raise SystemExit(1) from None
    took = f"{provider.name} answered in {time.perf_counter() - started:.1f} s"

    # The provider returns the reply unvalidated; B1's clean_drafts() is what checks it.
    # Here it's enough to know the first card has both sides.
    card = cards[0] if cards else None
    if not (
        isinstance(card, dict) and isinstance(card.get("front"), str)
        and isinstance(card.get("back"), str)
    ):
        click.echo(f"{took}, but with no usable card.", err=True)
        raise SystemExit(1)
    click.echo(f"{took}: {card['front']} → {card['back']}")
