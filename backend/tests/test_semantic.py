"""Network-free tests for optional local semantic ranking."""

from __future__ import annotations

import json
import math

import pytest

from backend.app import semantic


def test_rank_chunks_returns_source_indices_and_scores() -> None:
    def embed(texts: list[str]) -> object:
        assert texts == ["휴가 일수는?", "연간 15일의 유급휴가", "계정 권한 안내"]
        return [[2.0, 0.0], [3.0, 1.0], [0.0, 2.0]]

    assert semantic.rank_chunks(
        "휴가 일수는?", ["연간 15일의 유급휴가", "계정 권한 안내"],
        embed=embed,
    ) == [(0, 0.949)]


def test_rank_chunks_does_not_force_a_semantic_match() -> None:
    result = semantic.rank_chunks(
        "휴가", ["계정 권한"], embed=lambda _: [[1.0, 0.0], [0.0, 1.0]]
    )
    assert result == []


@pytest.mark.parametrize("vectors", [
    None,
    [],
    [[1.0, 0.0]],
    [[1.0, 0.0], [1.0]],
    [[0.0, 0.0], [1.0, 0.0]],
    [[1.0, 0.0], [math.nan, 0.0]],
    [[1.0, 0.0], [math.inf, 0.0]],
    [[1.0, 0.0], [10 ** 1000, 0.0]],
    [[1.0, 0.0], [True, 0.0]],
])
def test_malformed_embeddings_request_lexical_fallback(vectors: object) -> None:
    assert semantic.rank_chunks("질문", ["문서"], embed=lambda _: vectors) is None


def test_embed_failure_requests_lexical_fallback() -> None:
    def fail(_: list[str]) -> object:
        raise ConnectionError("private model error")

    assert semantic.rank_chunks("질문", ["문서"], embed=fail) is None


def test_empty_input_does_not_contact_ollama() -> None:
    def fail(_: list[str]) -> object:
        pytest.fail("Embedding must not be called")

    assert semantic.rank_chunks("  ", ["문서"], embed=fail) == []
    assert semantic.rank_chunks("질문", [], embed=fail) == []


def test_oversized_corpus_requests_lexical_fallback() -> None:
    def fail(_: list[str]) -> object:
        pytest.fail("Embedding must not be called")

    assert semantic.rank_chunks(
        "질문", ["문서"] * (semantic.MAX_CHUNKS + 1), embed=fail
    ) is None


def test_invalid_similarity_cutoff_is_rejected() -> None:
    with pytest.raises(ValueError):
        semantic.rank_chunks("질문", ["문서"], minimum_similarity=math.nan)


def test_ollama_transport_uses_loopback_and_embed_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, object] = {}

    class FakeResponse:
        status = 200

        def read(self, _: int) -> bytes:
            return b'{"embeddings": [[1.0, 0.0], [1.0, 0.0]]}'

    class FakeConnection:
        def __init__(self, host: str, port: int, timeout: float) -> None:
            observed["connection"] = (host, port, timeout)

        def request(self, method: str, path: str, body: bytes, headers: dict[str, str]) -> None:
            observed.update(method=method, path=path, body=json.loads(body), headers=headers)

        def getresponse(self) -> FakeResponse:
            return FakeResponse()

        def close(self) -> None:
            observed["closed"] = True

    monkeypatch.setattr(semantic.http.client, "HTTPConnection", FakeConnection)
    assert semantic.rank_chunks("질문", ["근거"]) == [(0, 1.0)]
    assert observed["connection"] == (
        "127.0.0.1", 11434, semantic.EMBEDDING_TIMEOUT_SECONDS
    )
    assert observed["method"] == "POST"
    assert observed["path"] == "/api/embed"
    assert observed["body"] == {
        "model": "bge-m3", "input": ["질문", "근거"], "truncate": False,
    }
    assert observed["closed"] is True
