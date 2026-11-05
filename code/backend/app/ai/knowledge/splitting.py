"""Splitting loaded pages into the chunks that get searched."""

from collections.abc import Iterable

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

CHUNK_SIZE = 1_500   # characters
CHUNK_OVERLAP = 150  # keeps a sentence that crosses a cut findable from either side

# built once at import and safe to share since it keeps no state between calls
_splitter = RecursiveCharacterTextSplitter(
    chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP, add_start_index=True
)


def split_pages(pages: Iterable[Document]) -> list[Document]:
    """Chunks that keep their page's metadata, and add `chunk_index`.

    The same pages always give the same chunks and indexes, so a retry can recognize them.
    """
    # splits on paragraphs first then lines then words keeping each page's metadata
    chunks = _splitter.split_documents(pages)
    for index, chunk in enumerate(chunks):
        chunk.metadata["chunk_index"] = index  # the position across the whole file
    return chunks
