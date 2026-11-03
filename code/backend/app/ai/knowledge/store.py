"""The vector store over the `knowledge_chunks` table."""

from langchain_core.embeddings import Embeddings
from langchain_postgres import PGEngine, PGVectorStore
from langchain_postgres.v2.hybrid_search_config import HybridSearchConfig, reciprocal_rank_fusion
from sqlalchemy.ext.asyncio import AsyncEngine

TABLE_NAME = "knowledge_chunks"
METADATA_COLUMNS = [
    "embedding_model",
    "owner_id",
    "document_id",
    "chunk_index",
    "page",
    "source_card_id",
    "shared",
    "accepted_by",
]


async def create_store(engine: AsyncEngine, embeddings: Embeddings) -> PGVectorStore:
    """A store using hybrid search: vectors for meaning, and keywords for exact terms."""
    return await PGVectorStore.create(
        PGEngine.from_engine(engine),
        embedding_service=embeddings,
        table_name=TABLE_NAME,
        metadata_columns=METADATA_COLUMNS,
        hybrid_search_config=HybridSearchConfig(
            tsv_column="content_tsv", fusion_function=reciprocal_rank_fusion
        ),
    )
