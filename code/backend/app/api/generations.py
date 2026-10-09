"""Accepting and rejecting AI suggestions - B4 (Von).

The blueprint is registered by `app/api/__init__.py`. Like `cards_bp`, it has no
url_prefix:

    POST /api/generations/<generation_id>/accept  {indexes}  -> 201 {cards: [Card], generation: Generation}
    POST /api/generations/<generation_id>/reject  {indexes}  -> 200 Generation

Contract C4 in code/plans/ITERATION_3_PLAN.md. Only accepting creates cards, and only it
sets `origin = "ai"` (rule 18). Someone else's generation answers 404.
Step 0a creates the blueprint with no routes, so B4 only ever touches this file.
"""

# Step 0a: the empty blueprint and the docstring.
# AI Utilization: ~100% of that code
# AI Tools Used: Claude Code (Claude Opus 5.5)
# AI-Assisted Activities:
#   Blueprint scaffolding
#   Documentation
# Human role: plan approval, code review, and hands-on testing by Miles Cameron.

from flask import Blueprint

generations_bp = Blueprint("generations", __name__)
