"""What Gemini receives: the rules, the deck, and the mode's body (B1).

Step 0a writes the signature, so B3 can import it from the start. B1 writes the body,
word for word from "The prompt: what Gemini receives" in code/plans/ITERATION_3_PLAN.md.

Pure (rule 19): no Flask, no SQLAlchemy, no `app.models`.
"""

# AI Utilization: ~100% of this file's code
# AI Tools Used: Claude Code (Claude Opus 5.5)
# AI-Assisted Activities:
#   Function signature stub
# Human role: plan approval, code review, and hands-on testing by Miles Cameron.

from collections.abc import Sequence

from app.ai.provider import Attachment, CardDraft, Prompt


def build_prompt(
    mode: str, *, count: int, deck_name: str, deck_description: str | None,
    prompt: str | None = None,             # prompt mode
    file_text: str | None = None,          # file mode, TXT or MD
    attachment: Attachment | None = None,  # file mode, PDF
    focus: str | None = None,              # file mode, optional
    existing: Sequence[CardDraft] = (),    # suggest mode, newest first
) -> Prompt:
    """The `Prompt` for one generate request, with `max_cards = count`."""
    raise NotImplementedError("B1 writes build_prompt(). See code/plans/ITERATION_3_PLAN.md.")
