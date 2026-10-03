"""Run a small, reproducible API-level retrieval evaluation without a model key."""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from backend.app.main import NO_MATCH_ANSWER, create_app


DEFAULT_FIXTURE = Path(__file__).with_name("cases.json")


def evaluate(
    fixture_path: Path = DEFAULT_FIXTURE, *, semantic_retrieval: bool = False
) -> dict[str, object]:
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    failures: list[str] = []
    with tempfile.TemporaryDirectory(prefix="document-qa-eval-") as directory:
        client = TestClient(create_app(
            Path(directory) / "documents.sqlite3", public_demo=False,
            semantic_retrieval=semantic_retrieval,
        ))
        document_ids: dict[str, str] = {}
        for document in fixture["documents"]:
            response = client.post(
                "/api/documents",
                files={"file": (
                    document["filename"], document["content"].encode("utf-8"),
                    "text/markdown",
                )},
            )
            response.raise_for_status()
            document_ids[document["key"]] = response.json()["id"]

        hits = 0
        for case in fixture["answerable"]:
            response = client.post("/api/questions", json={"question": case["question"]})
            response.raise_for_status()
            sources = response.json()["sources"]
            if sources and sources[0]["documentId"] == document_ids[case["expectedDocument"]]:
                hits += 1
            else:
                failures.append(f"hit@1: {case['question']}")

        refusals = 0
        for case in fixture["unanswerable"]:
            response = client.post("/api/questions", json={"question": case["question"]})
            response.raise_for_status()
            result = response.json()
            if not result["sources"] and result["answer"] == NO_MATCH_ANSWER:
                refusals += 1
            else:
                failures.append(f"refusal: {case['question']}")

    return {
        "fixtureVersion": fixture["version"],
        "retrievalMode": "semantic-fallback" if semantic_retrieval else "lexical",
        "hitAt1": {"passed": hits, "total": len(fixture["answerable"])},
        "refusal": {"passed": refusals, "total": len(fixture["unanswerable"])},
        "failures": failures,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument(
        "--semantic", action="store_true",
        help="Try local bge-m3 only when keyword retrieval finds nothing",
    )
    args = parser.parse_args()
    result = evaluate(args.fixture, semantic_retrieval=args.semantic)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
