"""What models return, as Pydantic models for `with_structured_output`."""

from typing import Literal

from pydantic import BaseModel, Field, StrictInt


class CardDraft(BaseModel):
    front: str = Field(description="A question or cue with exactly one correct answer.")
    back: str = Field(description="The answer, in 5 words or fewer.")


class CardBatch(BaseModel):
    """The finished flashcards."""

    cards: list[CardDraft]


class Verdict(BaseModel):
    index: StrictInt = Field(description="The candidate's index.")
    ok: bool
    reason: str | None = Field(default=None, description="Why it failed, in one short sentence.")


class Verdicts(BaseModel):
    """One verdict for every candidate card."""

    verdicts: list[Verdict]


class CleanChunks(BaseModel):
    """The passages that are ordinary study material."""

    clean: list[StrictInt] = Field(description="Their indexes.")


class SameFacts(BaseModel):
    """The pairs whose two cards teach the same fact."""

    same: list[StrictInt] = Field(description="Their indexes.")


class FixOption(BaseModel):
    kind: Literal["rewrite", "split", "contrast", "prerequisite"]
    reason: str = Field(description="The likely cause and how this fixes it, in one sentence.")
    cards: list[CardDraft]


class CardFixes(BaseModel):
    index: StrictInt = Field(description="The card's index.")
    options: list[FixOption]


class Diagnosis(BaseModel):
    """Why cards keep being forgotten, and how to fix them."""

    shared_cause: str | None = Field(
        default=None, description="A topic or cause several cards share, if there is one."
    )
    recommendations: list[CardFixes]


class Topics(BaseModel):
    """Study topics to offer the learner."""

    topics: list[str]
