"""What stays fixed during a run. It isn't saved in the checkpoint, so models never are."""

from dataclasses import dataclass

from langchain_core.language_models import BaseChatModel


@dataclass(frozen=True, kw_only=True)
class ProblemCardContext:
    writer: BaseChatModel
    judge: BaseChatModel
    cards: list[dict]  # {"id", "front", "back", "lapses", "similar"}
    existing_fronts: list[str]  # all of the deck's fronts
