"""What stays fixed during a run. Nodes read it from the runtime, and never change it."""

from collections.abc import Sequence
from dataclasses import dataclass
from functools import cached_property

from langchain_core.language_models import BaseChatModel

from app.ai.cards.checks import normalized_fronts
from app.ai.judge import Evidence
from app.ai.knowledge.retrieval import KnowledgeRetriever
from app.ai.schemas import CardDraft


@dataclass(frozen=True, kw_only=True)
class CardContext:
    writer: BaseChatModel
    judge: BaseChatModel
    count: int
    body: str  # the request, as prompts.prompt_body() or prompts.file_body() built it
    evidence: Evidence
    existing: Sequence[CardDraft] = ()  # the deck's newest cards, for the judge
    existing_fronts: Sequence[str] = ()  # all of the deck's fronts, for removing exact repeats
    retriever: KnowledgeRetriever | None = None  # with one, the writer may search once

    @cached_property
    def taken_fronts(self) -> set[str]:
        """`existing_fronts` normalized once per run, however many rounds check against them."""
        return normalized_fronts(self.existing_fronts)
