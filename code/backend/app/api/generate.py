"""Generating cards with AI - B3 (Duc).

The blueprint is registered by `app/api/__init__.py`. Like `cards_bp`, it has no
url_prefix:

    POST /api/decks/<deck_id>/generate
         {mode: "prompt", count, prompt}
         {mode: "file", count, file: {name, mime_type, data}, focus?}
         {mode: "suggest", count}
      -> 201 Generation    404, 400, 422 + field, 429 rate_limited, 503 ai_unavailable

Contract C2 in code/plans/ITERATION_3_PLAN.md, which also fixes the order of the checks.
Step 0a creates the blueprint with no routes, so B3 only ever touches this file.
"""

# Step 0a: the empty blueprint and the docstring.
# AI Utilization: ~100% of that code
# AI Tools Used: Claude Code (Claude Opus 5.5)
# AI-Assisted Activities:
#   Blueprint scaffolding
#   Documentation
# Human role: plan approval, code review, and hands-on testing by Miles Cameron.

from flask import Blueprint

generate_bp = Blueprint("generate", __name__)
