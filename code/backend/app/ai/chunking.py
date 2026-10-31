"""Split long documents for the pipeline's extract step."""

import math

CHUNK_SIZE = 25_000  # characters
MAX_CHUNKS = 4       # bounds model calls per request


def split_text(text: str) -> list[str]:
    """Split `text` at natural breaks. Returns [] if it fits in one chunk."""
    if len(text) <= CHUNK_SIZE:
        return []

    count = min(MAX_CHUNKS, math.ceil(len(text) / CHUNK_SIZE))
    target = math.ceil(len(text) / count)
    chunks = []
    start = 0
    while len(chunks) < count - 1:
        end = start + target
        # Search only the last 20% of the chunk, so a break can't leave it far undersized.
        floor = end - target // 5
        cut = text.rfind("\n\n", floor, end)
        if cut == -1:
            cut = max(text.rfind("\n", floor, end), text.rfind(" ", floor, end))
        if cut == -1:
            cut = end
        chunks.append(text[start:cut])
        start = cut
    chunks.append(text[start:])
    return [chunk.strip() for chunk in chunks if chunk.strip()]
