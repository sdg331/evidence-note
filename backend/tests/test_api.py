"""Behavioral tests for the document evidence API."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import json
import sqlite3

import pytest
from fastapi.testclient import TestClient

from backend.app.main import MAX_FILE_BYTES, create_app
from backend.app import main as backend_main


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    return TestClient(create_app(tmp_path / "documents.sqlite3"))


def upload(client: TestClient, name: str, content: bytes, media_type: str = "text/plain"):
    return client.post("/api/documents", files={"file": (name, content, media_type)})


def make_pdf_with_text(message: str) -> bytes:
    return make_pdf_with_pages([message])


def make_pdf_with_pages(messages: list[str]) -> bytes:
    """Create a tiny valid PDF without adding a test-only runtime dependency."""
    font_id = 3 + 2 * len(messages)
    page_ids = range(3, 3 + len(messages))
    stream_ids = range(3 + len(messages), font_id)
    kids = " ".join(f"{page_id} 0 R" for page_id in page_ids)
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        f"<< /Type /Pages /Kids [{kids}] /Count {len(messages)} >>".encode(),
    ]
    objects.extend(
        f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        f"/Contents {stream_id} 0 R /Resources << /Font << /F1 {font_id} 0 R >> >> >>".encode()
        for stream_id in stream_ids
    )
    for message in messages:
        stream = f"BT /F1 12 Tf 72 720 Td ({message}) Tj ET".encode("ascii")
        objects.append(
            f"<< /Length {len(stream)} >>\nstream\n".encode() + stream + b"\nendstream"
        )
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    pdf = b"%PDF-1.4\n"
    offsets = [0]
    for index, body in enumerate(objects, start=1):
        offsets.append(len(pdf))
        pdf += f"{index} 0 obj\n".encode() + body + b"\nendobj\n"
    xref_offset = len(pdf)
    pdf += f"xref\n0 {len(offsets)}\n0000000000 65535 f \n".encode()
    pdf += b"".join(f"{offset:010d} 00000 n \n".encode() for offset in offsets[1:])
    pdf += (
        f"trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\n"
        f"startxref\n{xref_offset}\n%%EOF\n"
    ).encode()
    return pdf


def test_korean_demo_questions_return_document_evidence(client: TestClient) -> None:
    content = (
        "# 팀 온보딩\n"
        "## 첫 주 일정\n"
        "입사 첫 주에는 개발 환경을 설정하고 팀의 코드 규칙을 읽습니다.\n"
        "## 계정 및 권한\n"
        "계정 권한은 입사 첫날 IT 담당자에게 요청합니다.\n"
    ).encode()
    created = upload(client, "team-onboarding.md", content, "text/markdown")
    assert created.status_code == 201
    document = created.json()
    assert document["title"] == "team-onboarding.md"
    assert document["characters"] > 0
    assert client.get("/api/documents").json() == {"documents": [document]}

    for question, expected in [
        ("첫 주에 해야 할 일은?", "개발 환경을 설정"),
        ("계정 권한은 언제 요청하나요?", "입사 첫날"),
    ]:
        response = client.post("/api/questions", json={"question": question})
        assert response.status_code == 200
        result = response.json()
        assert result["mode"] == "retrieval"
        assert expected in result["answer"]
        assert result["sources"][0]["documentId"] == document["id"]
        assert expected in result["sources"][0]["excerpt"]
        assert 0 < result["sources"][0]["score"] <= 1


def test_no_match_does_not_invent_an_answer(client: TestClient) -> None:
    upload(client, "onboarding.txt", "팀 정책: 계정은 첫날 요청합니다.".encode())
    response = client.post("/api/questions", json={"question": "휴가 정책은 어떻게 되나요?"})
    assert response.status_code == 200
    result = response.json()
    assert result["mode"] == "retrieval"
    assert result["sources"] == []
    assert "근거를 찾지 못했습니다" in result["answer"]


@pytest.mark.parametrize("heading,question", [
    ("휴가 정책", "휴가 정책은?"),
    ("연차 정책", "연차 정책은?"),
])
def test_korean_noun_and_heading_include_the_policy_fact(
    client: TestClient, heading: str, question: str
) -> None:
    document = upload(
        client, "leave.md", f"# {heading}\n연간 15일의 유급휴가를 제공합니다.".encode()
    ).json()
    response = client.post("/api/questions", json={"question": question})
    assert response.status_code == 200
    result = response.json()
    assert result["sources"][0]["documentId"] == document["id"]
    assert "연간 15일" in result["sources"][0]["excerpt"]
    assert "연간 15일" in result["answer"]


def test_new_document_returns_full_source_text(client: TestClient) -> None:
    content = "# 연차 정책\n연간 15일의 유급휴가를 제공합니다.\n\n둘째 문단입니다."
    document = upload(client, "leave.md", content.encode()).json()
    response = client.get(f"/api/documents/{document['id']}")
    assert response.status_code == 200
    assert response.json() == {
        **document, "content": content, "pages": [], "contentComplete": True,
    }
    assert client.get("/api/documents/missing").status_code == 404


def test_pdf_text_can_be_uploaded_and_searched(client: TestClient) -> None:
    created = upload(client, "access.pdf", make_pdf_with_pages([
        "Attendance starts at nine.", "Access is granted on day one."
    ]),
                     "application/pdf")
    assert created.status_code == 201
    answer = client.post("/api/questions", json={"question": "access granted"}).json()
    assert "Access is granted on day one" in answer["answer"]
    assert answer["sources"][0]["page"] == 2
    detail = client.get(f"/api/documents/{created.json()['id']}").json()
    assert detail["pages"] == [
        {"page": 1, "content": "Attendance starts at nine."},
        {"page": 2, "content": "Access is granted on day one."},
    ]
    assert detail["content"] == "Attendance starts at nine.\n\nAccess is granted on day one."


def test_old_schema_migrates_without_losing_search_data(tmp_path: Path) -> None:
    db_path = tmp_path / "legacy.sqlite3"
    with sqlite3.connect(db_path) as connection:
        connection.executescript(
            """
            CREATE TABLE documents (
                id TEXT PRIMARY KEY, title TEXT NOT NULL, characters INTEGER NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE chunks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
                position INTEGER NOT NULL, content TEXT NOT NULL
            );
            INSERT INTO documents (id, title, characters) VALUES ('legacy', 'old.txt', 17);
            INSERT INTO chunks (document_id, position, content)
            VALUES ('legacy', 0, '접근 권한은 첫날 요청합니다.');
            """
        )
    client = TestClient(create_app(db_path))
    result = client.post("/api/questions", json={"question": "접근 권한은?"}).json()
    assert result["sources"][0]["documentId"] == "legacy"
    assert result["sources"][0]["page"] is None
    detail = client.get("/api/documents/legacy").json()
    assert detail["content"] == "접근 권한은 첫날 요청합니다."
    assert detail["contentComplete"] is False
    assert detail["pages"] == []


@pytest.mark.parametrize(
    ("name", "content", "expected_status"),
    [
        ("script.exe", b"print('hello')", 415),
        ("empty.txt", b"  \n", 422),
        ("invalid.txt", b"\xff\xfe", 422),
        ("image-only.pdf", b"not a PDF", 422),
        ("oversize.md", b"x" * (MAX_FILE_BYTES + 1), 413),
    ],
)
def test_invalid_uploads_are_rejected(
    client: TestClient, name: str, content: bytes, expected_status: int
) -> None:
    response = upload(client, name, content)
    assert response.status_code == expected_status
    assert client.get("/api/documents").json() == {"documents": []}


def test_documents_persist_and_delete_with_their_evidence(tmp_path: Path) -> None:
    db_path = tmp_path / "stored.sqlite3"
    first_client = TestClient(create_app(db_path))
    document = upload(first_client, "guide.txt", "접근 권한은 첫날 요청합니다.".encode()).json()

    restarted_client = TestClient(create_app(db_path))
    assert restarted_client.get("/api/documents").json()["documents"] == [document]
    assert restarted_client.post(
        "/api/questions", json={"question": "접근 권한은?"}
    ).json()["sources"][0]["documentId"] == document["id"]

    assert restarted_client.delete(f"/api/documents/{document['id']}").status_code == 204
    assert restarted_client.get("/api/documents").json() == {"documents": []}
    assert first_client.post(
        "/api/questions", json={"question": "접근 권한은?"}
    ).json()["sources"] == []
    assert restarted_client.delete(f"/api/documents/{document['id']}").status_code == 404


def test_question_validation_and_health(client: TestClient) -> None:
    assert client.get("/api/health").json() == {"status": "ok"}
    assert client.post("/api/questions", json={"question": "   "}).status_code == 422
    assert client.post("/api/questions", json={"question": "x" * 501}).status_code == 422


def test_model_option_requires_configuration_when_evidence_exists(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    assert client.get("/api/capabilities").json() == {
        "modelAvailable": False, "modelProvider": None,
        "uploadsAvailable": True, "publicDemo": False,
    }
    upload(client, "guide.txt", "계정 권한은 첫날 요청합니다.".encode())

    response = client.post(
        "/api/questions", json={"question": "계정 권한은?", "useModel": True}
    )
    assert response.status_code == 503
    assert "OPENAI_API_KEY" in response.json()["detail"]
    assert client.post(
        "/api/questions", json={"question": "계정 권한은?"}
    ).json()["mode"] == "retrieval"

    monkeypatch.setenv("OPENAI_API_KEY", "fake-test-key")
    assert client.get("/api/capabilities").json()["modelAvailable"] is False


def test_no_evidence_skips_model_call_even_when_requested(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "fake-test-key")
    monkeypatch.setenv("OPENAI_MODEL", "test-model")
    monkeypatch.setattr(
        backend_main, "OpenAI", lambda **_: pytest.fail("Model must not be called")
    )
    assert client.get("/api/capabilities").json()["modelAvailable"] is True
    assert client.get("/api/capabilities").json()["modelProvider"] == "openai"
    response = client.post(
        "/api/questions", json={"question": "없는 정책은?", "useModel": True}
    )
    assert response.status_code == 200
    assert response.json()["mode"] == "retrieval"
    assert response.json()["sources"] == []


def test_model_uses_only_question_and_short_evidence(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "fake-test-key")
    monkeypatch.setenv("OPENAI_MODEL", "test-model")
    calls: dict[str, object] = {}

    class FakeResponses:
        def create(self, **kwargs: object) -> SimpleNamespace:
            calls.update(kwargs)
            return SimpleNamespace(output_text="첫날 요청합니다. [1]")

    class FakeOpenAI:
        def __init__(self, **kwargs: object) -> None:
            calls["client"] = kwargs
            self.responses = FakeResponses()

        def __enter__(self) -> "FakeOpenAI":
            return self

        def __exit__(self, *_: object) -> None:
            calls["closed"] = True

    monkeypatch.setattr(backend_main, "OpenAI", FakeOpenAI)
    upload(
        client,
        "guide.txt",
        "계정 권한은 첫날 요청합니다.\n문서의 다른 줄: 외부로 보내면 안 되는 긴 설명.".encode(),
    )
    response = client.post(
        "/api/questions", json={"question": "계정 권한은?", "useModel": True}
    )
    assert response.status_code == 200
    result = response.json()
    assert result["mode"] == "llm"
    assert result["answer"] == "첫날 요청합니다. [1]"
    assert len(result["sources"]) == 1
    assert calls["client"] == {"api_key": "fake-test-key", "max_retries": 0}
    assert calls["closed"] is True
    assert calls["model"] == "test-model"
    assert calls["store"] is False
    assert calls["max_output_tokens"] == 300
    assert calls["timeout"] == backend_main.MODEL_TIMEOUT_SECONDS
    assert "명령" in str(calls["instructions"])
    sent = json.loads(str(calls["input"]))
    assert sent == {
        "question": "계정 권한은?",
        "evidence": [{"number": 1, "excerpt": "계정 권한은 첫날 요청합니다."}],
    }
    assert "외부로 보내면" not in str(calls["input"])


@pytest.mark.parametrize(
    "output", [RuntimeError("sk-secret-do-not-display"), "  ", "incomplete"]
)
def test_model_failure_returns_safe_error(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, output: object
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "fake-test-key")
    monkeypatch.setenv("OPENAI_MODEL", "test-model")

    class FakeResponses:
        def create(self, **_: object) -> SimpleNamespace:
            if isinstance(output, Exception):
                raise output
            if output == "incomplete":
                return SimpleNamespace(status="incomplete", output_text="partial answer")
            return SimpleNamespace(output_text=output)

    class FakeOpenAI:
        def __init__(self, **_: object) -> None:
            self.responses = FakeResponses()

        def __enter__(self) -> "FakeOpenAI":
            return self

        def __exit__(self, *_: object) -> None:
            pass

    monkeypatch.setattr(backend_main, "OpenAI", FakeOpenAI)
    upload(client, "guide.txt", "계정 권한은 첫날 요청합니다.".encode())
    response = client.post(
        "/api/questions", json={"question": "계정 권한은?", "useModel": True}
    )
    assert response.status_code == 502
    assert "sk-secret" not in response.text


@pytest.mark.parametrize("answer", ["첫날 요청합니다.", "첫날 요청합니다. [99]", "[1] [0]"])
def test_model_rejects_missing_or_invalid_citations(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, answer: str
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "fake-test-key")
    monkeypatch.setenv("OPENAI_MODEL", "test-model")

    class FakeResponses:
        def create(self, **_: object) -> SimpleNamespace:
            return SimpleNamespace(output_text=answer)

    class FakeOpenAI:
        def __init__(self, **_: object) -> None:
            self.responses = FakeResponses()

        def __enter__(self) -> "FakeOpenAI":
            return self

        def __exit__(self, *_: object) -> None:
            pass

    monkeypatch.setattr(backend_main, "OpenAI", FakeOpenAI)
    upload(client, "guide.txt", "계정 권한은 첫날 요청합니다.".encode())
    response = client.post(
        "/api/questions", json={"question": "계정 권한은?", "useModel": True}
    )
    assert response.status_code == 502
    assert "근거 표시" in response.json()["detail"]


def test_ollama_uses_local_chat_with_only_question_and_evidence(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ANSWER_PROVIDER", "ollama")
    monkeypatch.setenv("OLLAMA_MODEL", "exaone3.5:2.4b")
    monkeypatch.setenv("OPENAI_API_KEY", "unused-key")
    monkeypatch.setenv("OPENAI_MODEL", "unused-model")
    monkeypatch.setattr(
        backend_main, "OpenAI", lambda **_: pytest.fail("OpenAI must not be called")
    )
    requests: list[dict[str, object]] = []

    class FakeResponse:
        def __init__(self, payload: dict[str, object]) -> None:
            self.payload = payload

        def raise_for_status(self) -> None:
            pass

        def json(self) -> dict[str, object]:
            return self.payload

    class FakeClient:
        def __init__(self, **kwargs: object) -> None:
            requests.append({"clientOptions": kwargs})

        def __enter__(self) -> "FakeClient":
            return self

        def __exit__(self, *_: object) -> None:
            pass

        def get(self, url: str) -> FakeResponse:
            requests.append({"get": url})
            return FakeResponse({"models": [{"name": "exaone3.5:2.4b"}]})

        def post(self, url: str, **kwargs: object) -> FakeResponse:
            requests.append({"post": url, **kwargs})
            return FakeResponse({
                "done": True,
                "message": {"role": "assistant", "content": json.dumps({
                    "answer": "첫날 요청합니다.", "citations": [1],
                })},
            })

    monkeypatch.setattr(backend_main.httpx, "Client", FakeClient)
    upload(
        client, "guide.txt",
        "계정 권한은 첫날 요청합니다.\n문서의 다른 줄: 전송하면 안 되는 긴 설명.".encode(),
    )
    assert client.get("/api/capabilities").json() == {
        "modelAvailable": True, "modelProvider": "ollama",
        "uploadsAvailable": True, "publicDemo": False,
    }
    response = client.post(
        "/api/questions", json={"question": "계정 권한은?", "useModel": True}
    )
    assert response.status_code == 200
    assert response.json()["answer"] == "첫날 요청합니다. [1]"
    assert response.json()["mode"] == "llm"
    chat = next(request for request in requests if "post" in request)
    assert chat["post"] == "http://127.0.0.1:11434/api/chat"
    payload = chat["json"]
    assert payload["model"] == "exaone3.5:2.4b"
    assert payload["stream"] is False
    assert payload["format"] == "json"
    assert payload["options"] == {"temperature": 0, "num_predict": 300}
    assert payload["messages"][0]["role"] == "system"
    sent = json.loads(payload["messages"][1]["content"])
    assert sent == {
        "question": "계정 권한은?",
        "evidence": [{"number": 1, "excerpt": "계정 권한은 첫날 요청합니다."}],
    }
    assert "전송하면 안 되는" not in payload["messages"][1]["content"]
    assert all(
        request["clientOptions"]["trust_env"] is False
        for request in requests if "clientOptions" in request
    )


def test_ollama_unavailable_reports_false_and_skips_chat(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ANSWER_PROVIDER", "ollama")
    monkeypatch.setenv("OLLAMA_MODEL", "exaone3.5:2.4b")

    class FakeClient:
        def __init__(self, **_: object) -> None:
            pass

        def __enter__(self) -> "FakeClient":
            return self

        def __exit__(self, *_: object) -> None:
            pass

        def get(self, _: str) -> SimpleNamespace:
            return SimpleNamespace(
                raise_for_status=lambda: None,
                json=lambda: {"models": [{"name": "some-other-model"}]},
            )

        def post(self, *_: object, **__: object) -> None:
            pytest.fail("Unavailable Ollama must not receive a chat request")

    monkeypatch.setattr(backend_main.httpx, "Client", FakeClient)
    upload(client, "guide.txt", "계정 권한은 첫날 요청합니다.".encode())
    assert client.get("/api/capabilities").json()["modelAvailable"] is False
    response = client.post(
        "/api/questions", json={"question": "계정 권한은?", "useModel": True}
    )
    assert response.status_code == 503
    assert "로컬 AI 모델" in response.json()["detail"]


def test_ollama_connection_failure_reports_unavailable(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ANSWER_PROVIDER", "ollama")
    monkeypatch.setenv("OLLAMA_MODEL", "exaone3.5:2.4b")

    class BrokenClient:
        def __init__(self, **_: object) -> None:
            pass

        def __enter__(self) -> "BrokenClient":
            return self

        def __exit__(self, *_: object) -> None:
            pass

        def get(self, _: str) -> None:
            raise backend_main.httpx.ConnectError("local service unavailable")

    monkeypatch.setattr(backend_main.httpx, "Client", BrokenClient)
    assert client.get("/api/capabilities").json()["modelAvailable"] is False


@pytest.mark.parametrize("payload", [
    {"done": True},
    {"done": False, "message": {"content": '{"answer":"첫날 요청합니다.","citations":[1]}'}},
    {"done": True, "message": {"content": '{"answer":"첫날 요청합니다.","citations":[99]}'}},
    {"done": True, "message": {"content": "not json"}},
    {"done": True, "message": {"content": '{"answer":"","citations":[1]}'}},
])
def test_ollama_rejects_malformed_or_uncited_reply(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, payload: dict[str, object]
) -> None:
    monkeypatch.setenv("ANSWER_PROVIDER", "ollama")
    monkeypatch.setenv("OLLAMA_MODEL", "exaone3.5:2.4b")
    monkeypatch.setattr(backend_main, "_ollama_available", lambda _: True)

    class FakeClient:
        def __init__(self, **_: object) -> None:
            pass

        def __enter__(self) -> "FakeClient":
            return self

        def __exit__(self, *_: object) -> None:
            pass

        def post(self, *_: object, **__: object) -> SimpleNamespace:
            return SimpleNamespace(raise_for_status=lambda: None, json=lambda: payload)

    monkeypatch.setattr(backend_main.httpx, "Client", FakeClient)
    upload(client, "guide.txt", "계정 권한은 첫날 요청합니다.".encode())
    response = client.post(
        "/api/questions", json={"question": "계정 권한은?", "useModel": True}
    )
    assert response.status_code == 502


def test_semantic_retrieval_is_opt_in_and_only_used_after_lexical_miss(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = tmp_path / "semantic.sqlite3"
    lexical_client = TestClient(create_app(db_path))
    document = upload(
        lexical_client, "onboarding.md", "입사 첫날에는 개발 환경을 설정합니다.".encode()
    ).json()
    question = "입사하면 컴퓨터 개발 환경을 언제 준비하나요?"
    assert lexical_client.post(
        "/api/questions", json={"question": question}
    ).json()["sources"] == []

    calls: list[tuple[str, list[str]]] = []

    def fake_rank(question_text: str, chunks: list[str]) -> list[tuple[int, float]]:
        calls.append((question_text, chunks))
        return [(0, 0.695)]

    monkeypatch.setattr(backend_main, "rank_chunks", fake_rank)
    semantic_client = TestClient(create_app(db_path, semantic_retrieval=True))
    result = semantic_client.post("/api/questions", json={"question": question}).json()
    assert result["sources"][0]["documentId"] == document["id"]
    assert result["sources"][0]["score"] == 0.695
    assert "개발 환경을 설정" in result["answer"]
    assert calls == [(question, ["입사 첫날에는 개발 환경을 설정합니다."])]

    calls.clear()
    semantic_client.post("/api/questions", json={"question": "입사 첫날 개발 환경은?"})
    assert calls == []


def test_semantic_failure_keeps_no_match_and_public_demo_skips_embedding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = tmp_path / "semantic-fallback.sqlite3"
    private_client = TestClient(create_app(db_path, semantic_retrieval=True))
    upload(private_client, "guide.md", "계정 권한은 첫날 요청합니다.".encode())
    monkeypatch.setattr(backend_main, "rank_chunks", lambda *_: None)
    assert private_client.post(
        "/api/questions", json={"question": "재택 장비 배송 일정은?"}
    ).json()["sources"] == []

    monkeypatch.setattr(
        backend_main, "rank_chunks", lambda *_: pytest.fail("Public demo must skip embeddings")
    )
    public_client = TestClient(create_app(
        db_path, public_demo=True, semantic_retrieval=True
    ))
    assert public_client.post(
        "/api/questions", json={"question": "재택 장비 배송 일정은?"}
    ).json()["sources"] == []


def test_public_demo_never_checks_or_calls_ollama(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = tmp_path / "public-ollama.sqlite3"
    private_client = TestClient(create_app(db_path))
    upload(private_client, "guide.md", "계정 권한은 첫날 요청합니다.".encode())
    monkeypatch.setenv("ANSWER_PROVIDER", "ollama")
    monkeypatch.setenv("OLLAMA_MODEL", "exaone3.5:2.4b")
    monkeypatch.setattr(
        backend_main, "_ollama_available",
        lambda _: pytest.fail("Public demo must not check Ollama"),
    )
    public_client = TestClient(create_app(db_path, public_demo=True))
    capabilities = public_client.get("/api/capabilities").json()
    assert capabilities["modelProvider"] == "ollama"
    assert capabilities["modelAvailable"] is False
    assert public_client.post(
        "/api/questions", json={"question": "계정 권한은?", "useModel": True}
    ).status_code == 403


def test_public_demo_is_read_only_even_with_model_credentials(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = tmp_path / "public.sqlite3"
    private_client = TestClient(create_app(db_path))
    document = upload(private_client, "guide.txt", "계정 권한은 첫날 요청합니다.".encode()).json()
    monkeypatch.setenv("PUBLIC_DEMO", "1")
    monkeypatch.setenv("OPENAI_API_KEY", "fake-test-key")
    monkeypatch.setenv("OPENAI_MODEL", "test-model")
    public_client = TestClient(create_app(db_path))
    assert public_client.get("/api/capabilities").json() == {
        "modelAvailable": False, "modelProvider": "openai",
        "uploadsAvailable": False, "publicDemo": True,
    }
    assert public_client.get("/api/documents").json()["documents"] == [document]
    assert public_client.get(f"/api/documents/{document['id']}").status_code == 200
    assert public_client.post(
        "/api/questions", json={"question": "계정 권한은?"}
    ).json()["sources"][0]["documentId"] == document["id"]
    no_match = public_client.post(
        "/api/questions", json={"question": "항공권 예약 기준은?"}
    ).json()
    assert no_match["sources"] == []
    assert "문서를 추가" not in no_match["answer"]
    assert upload(public_client, "new.txt", b"new").status_code == 403
    assert public_client.delete(f"/api/documents/{document['id']}").status_code == 403
    assert public_client.post(
        "/api/questions", json={"question": "계정 권한은?", "useModel": True}
    ).status_code == 403
    assert private_client.get("/api/documents").json()["documents"] == [document]
