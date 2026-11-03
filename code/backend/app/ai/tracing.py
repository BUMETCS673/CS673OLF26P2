"""LangSmith trace roots, labelled so a run can be found by feature, user, deck or job.

LangChain and LangGraph runs inside one nest under it. Records nothing unless LANGSMITH_TRACING
is on.
"""

from typing import Any

from langsmith import trace


def labelled_trace(name: str, user_id: int, **ids: Any) -> trace:
    """One root per piece of AI work, tagged with `name`. Use with `async with`."""
    labels = {key: value for key, value in ids.items() if value is not None}
    return trace(name, tags=[name], metadata={"user_id": user_id, **labels})
