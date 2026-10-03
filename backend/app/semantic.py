"""Optional, local-only semantic ranking for document search.

The caller should use lexical retrieval when this module returns ``None``.
Similarity selects a source to show; it does not establish that the source
answers the question. Always quote the source text rather than inventing facts.
"""

from __future__ import annotations

import http.client
import json
import math
from collections.abc import Callable, Sequence


OLLAMA_HOST = "127.0.0.1"
OLLAMA_PORT = 11434
EMBEDDING_MODEL = "bge-m3"
EMBEDDING_TIMEOUT_SECONDS = 12.0
MAX_CHUNKS = 64
MAX_RESPONSE_BYTES = 4 * 1024 * 1024
DEFAULT_MINIMUM_SIMILARITY = 0.65


def _ollama_embed(texts: list[str]) -> object:
    """Call only the loopback Ollama embedding endpoint, with no proxy or cloud URL."""
    connection = http.client.HTTPConnection(
        OLLAMA_HOST, OLLAMA_PORT, timeout=EMBEDDING_TIMEOUT_SECONDS
    )
    try:
        body = json.dumps(
            {"model": EMBEDDING_MODEL, "input": texts, "truncate": False},
            ensure_ascii=False,
        ).encode("utf-8")
        connection.request(
            "POST", "/api/embed", body=body,
            headers={"Content-Type": "application/json"},
        )
        response = connection.getresponse()
        if response.status != 200:
            raise ValueError("Ollama embedding request failed")
        payload = response.read(MAX_RESPONSE_BYTES + 1)
        if len(payload) > MAX_RESPONSE_BYTES:
            raise ValueError("Ollama embedding response is too large")
        decoded = json.loads(payload)
        if not isinstance(decoded, dict):
            raise ValueError("Ollama embedding response is invalid")
        return decoded.get("embeddings")
    finally:
        connection.close()


def _valid_vectors(vectors: object, expected_count: int) -> list[list[float]] | None:
    if not isinstance(vectors, list) or len(vectors) != expected_count:
        return None
    dimension = 0
    valid: list[list[float]] = []
    for vector in vectors:
        if not isinstance(vector, list) or not vector:
            return None
        if not dimension:
            dimension = len(vector)
        if len(vector) != dimension:
            return None
        if any(isinstance(value, bool) or not isinstance(value, (int, float))
               for value in vector):
            return None
        try:
            converted = [float(value) for value in vector]
        except (OverflowError, ValueError):
            return None
        if any(not math.isfinite(value) for value in converted):
            return None
        norm = math.hypot(*converted)
        if not math.isfinite(norm) or norm <= 0:
            return None
        valid.append([value / norm for value in converted])
    return valid


def rank_chunks(
    question: str,
    chunks: Sequence[str],
    *,
    minimum_similarity: float = DEFAULT_MINIMUM_SIMILARITY,
    embed: Callable[[list[str]], object] | None = None,
) -> list[tuple[int, float]] | None:
    """Rank source chunks by cosine similarity.

    Returns ``None`` if embeddings are unavailable or malformed, allowing the
    caller to keep its lexical behavior. An empty list means that embeddings
    worked but no chunk passed the conservative similarity cutoff. The cutoff
    is a provisional heuristic and should be measured on the project's data.
    """
    if not question.strip() or not chunks:
        return []
    if len(chunks) > MAX_CHUNKS or any(
        not isinstance(chunk, str) or not chunk.strip() for chunk in chunks
    ):
        return None
    if not math.isfinite(minimum_similarity) or not 0 <= minimum_similarity <= 1:
        raise ValueError("minimum_similarity must be between 0 and 1")

    try:
        vectors = (embed or _ollama_embed)([question, *chunks])
    except Exception:
        # Connection and model errors may contain private text. Do not expose them.
        return None
    normalized = _valid_vectors(vectors, len(chunks) + 1)
    if normalized is None:
        return None

    question_vector = normalized[0]
    ranked = [
        (index, sum(a * b for a, b in zip(question_vector, vector)))
        for index, vector in enumerate(normalized[1:])
    ]
    ranked.sort(key=lambda item: (-item[1], item[0]))
    return [
        (index, round(min(1.0, max(0.0, score)), 3))
        for index, score in ranked if score >= minimum_similarity
    ]
