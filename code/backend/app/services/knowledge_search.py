"""Searching the shared knowledge base for one user as MCP clients do."""

import logging

from langchain_core.stores import ByteStore
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.knowledge.retrieval import labelled_text
from app.ai.models import Role, ai_errors
from app.ai.usage import RunUsage
from app.core.database import get_engine
from app.core.errors import BudgetExceeded
from app.core.settings import Settings
from app.jobs.generation import build_retriever
from app.services.budget import MCP_SEARCH, USER, BudgetService

logger = logging.getLogger(__name__)

SEARCH_RESULTS = 8  # passages per search which keeps a reply to a few thousand tokens
SEARCH_COST = {Role.EMBEDDER: 1}  # one query embedding or none when the cache has it
USER_LIMIT = "You've reached today's limit for searches. Try again later."
SITE_LIMIT = "Search has hit today's limit for the whole site. Try again later."


class KnowledgeSearchService:
    def __init__(
        self, session: AsyncSession, budget: BudgetService, settings: Settings, cache: ByteStore
    ):
        self.session = session  # one transaction for the budget check and the usage row
        self.budget = budget
        self.settings = settings
        self.cache = cache  # cached query vectors spare a repeated search its embedding call

    async def search(self, user_id: int, query: str) -> list[str]:
        """Passages on the query that each start with a line saying where it came from."""
        # Step 1: refuse once the learner's daily searches are used up
        reached, _ = await self.budget.limit_reached(
            MCP_SEARCH,
            user_id,
            SEARCH_COST,
            user_limit=self.settings.ai_mcp_search_user_daily_limit,  # no site cap for searches
        )
        if reached:
            logger.info("knowledge search refused", extra={"user_id": user_id, "limit": reached})
            raise BudgetExceeded(USER_LIMIT if reached == USER else SITE_LIMIT)  # 429

        # Step 2: run the same hybrid search as card generation over everyone's shared chunks
        usage = RunUsage()  # counts the embedding call for the budget
        try:
            retriever = await build_retriever(
                get_engine(),
                self.settings,
                usage,
                document_id=None,  # everyone's shared chunks rather than one file
                k=SEARCH_RESULTS,
                viewer_id=user_id,  # caps other learners' passages and labels the user's own
                cache=self.cache,
                learner_waiting=True,  # an agent is waiting on the reply, like a learner would
            )
            with ai_errors():  # vendor errors become ours
                found = await retriever.ainvoke(query)
        finally:
            # Step 3: save what the search spent, even when it failed
            self.budget.record(MCP_SEARCH, user_id, None, usage)
            await self.session.commit()
        logger.info("knowledge searched", extra={"user_id": user_id, "results": len(found)})
        # the origin label comes first and text inside an upload can't fake or hide it
        return [labelled_text(document) for document in found]  # the tool returns these
