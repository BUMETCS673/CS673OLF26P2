"""What the graph's nodes share. The checkpointer saves it, so it is also the chat's memory."""

from langgraph.graph import MessagesState


class TutorState(MessagesState):
    raw_cards: list[dict]  # what the model proposed, not yet checked
    proposal: dict | None  # {"id", "cards"}, waiting for the learner
    verification: str
