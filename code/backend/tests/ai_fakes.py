"""Test doubles for chat models."""

from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.utils.function_calling import convert_to_openai_tool


class ScriptedModel:
    """Answers each call with the next reply, or raises it if it's an exception.

    Works for plain calls and `with_structured_output`, and records every prompt.
    """

    def __init__(self, *replies):
        self.replies = list(replies)
        self.prompts = []
        self.schemas = []

    def with_structured_output(self, schema, **_):
        self.schemas.append(schema)
        return self

    async def ainvoke(self, messages, **_):
        self.prompts.append(messages)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


class ScriptedChatModel(BaseChatModel):
    """For agents: each call returns the next AIMessage, and records the tools it was offered."""

    replies: list[AIMessage]
    offered: list[list[str]] = []
    choices: list[Any] = []

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(self, tools, *, tool_choice=None, **_):
        names = [convert_to_openai_tool(tool)["function"]["name"] for tool in tools]
        self.offered.append(names)
        self.choices.append(tool_choice)
        return self

    def _generate(self, messages, stop=None, run_manager=None, **_):
        return ChatResult(generations=[ChatGeneration(message=self.replies.pop(0))])
