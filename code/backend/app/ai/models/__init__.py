"""Chat models and embeddings for each role, and the errors they can raise."""

from app.ai.models.calls import (
    BAD_REPLY,
    ChainFallbackMiddleware,
    agent_model,
    structured_reply,
    structured_reply_or_none,
)
from app.ai.models.chains import (
    ModelSpec,
    Role,
    RunModels,
    check_model_chains,
    first_models,
    judge_chain,
    model_chain,
    model_name,
    plan_models,
)
from app.ai.models.errors import (
    AT_CAPACITY,
    NOT_CONFIGURED,
    AIRateLimited,
    AITransient,
    AIUnavailable,
    ai_errors,
)
from app.ai.models.factory import ChatModel, GuardedEmbeddings, load_chat_model, load_embeddings

__all__ = [
    "AT_CAPACITY",
    "BAD_REPLY",
    "NOT_CONFIGURED",
    "AIRateLimited",
    "AITransient",
    "AIUnavailable",
    "ChainFallbackMiddleware",
    "ChatModel",
    "GuardedEmbeddings",
    "ModelSpec",
    "Role",
    "RunModels",
    "agent_model",
    "ai_errors",
    "check_model_chains",
    "first_models",
    "judge_chain",
    "load_chat_model",
    "load_embeddings",
    "model_chain",
    "model_name",
    "plan_models",
    "structured_reply",
    "structured_reply_or_none",
]
