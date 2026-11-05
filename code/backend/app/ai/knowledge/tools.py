"""The tool a model calls to search the knowledge base."""

from dataclasses import dataclass

from langchain_core.documents import Document
from langchain_core.tools import tool
from langgraph.runtime import get_runtime

from app.ai.knowledge.retrieval import KnowledgeRetriever, labelled_text
from app.ai.models import AIRateLimited, AIUnavailable, ai_errors
from app.ai.prompting import text_block

NOTHING_FOUND = "Nothing relevant was found."


@dataclass(kw_only=True)
class KnowledgeContext:
    """What a graph must provide for this tool. The filters are set by code, not the model."""

    retriever: KnowledgeRetriever


# content_and_artifact gives the model text and keeps the Documents for our code
@tool(response_format="content_and_artifact")
async def search_materials(query: str) -> tuple[str, list[Document]]:
    """Find passages about a query in the study materials."""
    # from the run's context so the model can only choose the query
    retriever = get_runtime(KnowledgeContext).context.retriever
    try:
        with ai_errors():
            found = await retriever.ainvoke(query)  # one embedding call and one search
    except (AIRateLimited, AIUnavailable):
        # The writer can still use general knowledge, so a failed search doesn't end the run.
        return NOTHING_FOUND, []
    if not found:  # an uncovered topic which the writer is told plainly
        return NOTHING_FOUND, []
    # In the tags the model's rules say to treat as material, since any user's upload can be here.
    return "\n\n".join(text_block("source", labelled_text(document)) for document in found), found
