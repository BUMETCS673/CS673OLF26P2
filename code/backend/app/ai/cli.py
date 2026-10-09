"""`flask ai-smoke`: one real request to the configured AI provider (B2).

Step 0a registers the command, in `_register_cli()` in app/__init__.py, so B2 only ever
touches this file. B2 makes it ask for one card and print it, like

    gemini-3.5-flash answered in 2.4 s: What is the capital of France? → Paris
"""

# AI Utilization: ~100% of this file's code
# AI Tools Used: Claude Code (Claude Opus 5.5)
# AI-Assisted Activities:
#   CLI command stub
# Human role: plan approval, code review, and hands-on testing by Miles Cameron.

import click
from flask.cli import with_appcontext


@click.command("ai-smoke")
@with_appcontext
def ai_smoke_command():
    """Ask the configured AI provider for one card, and print it."""
    click.echo("Not built yet: B2")
    raise SystemExit(1)
