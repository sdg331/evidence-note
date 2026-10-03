"""Measure retrieval on the reviewed public-guide excerpt fixture.

Usage: python -m scripts.evaluate_demo
       SEMANTIC_RETRIEVAL=1 python -m scripts.evaluate_demo
The optional semantic mode requires a local Ollama bge-m3 model.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from backend.app.main import create_app
from scripts.seed_demo import seed


FIXTURE_PATH = Path(__file__).resolve().parents[1] / "demo" / "evaluation_cases.json"


def evaluate() -> dict[str, object]:
    fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    failures: list[str] = []
    with tempfile.TemporaryDirectory(prefix="gonggam-eval-") as directory:
        database_path = Path(directory) / "documents.sqlite3"
        seed(database_path)
        with TestClient(create_app(database_path, public_demo=False)) as client:
            correct_pages = 0
            for case in fixture["answerable"]:
                response = client.post("/api/questions", json={"question": case["question"]})
                response.raise_for_status()
                sources = response.json()["sources"]
                actual_page = sources[0]["page"] if sources else None
                if actual_page == case["expectedPage"]:
                    correct_pages += 1
                else:
                    failures.append(
                        f"expected {case['expectedPage']}쪽, got {actual_page}: {case['question']}"
                    )

            refusals = 0
            for question in fixture["unanswerable"]:
                response = client.post("/api/questions", json={"question": question})
                response.raise_for_status()
                if not response.json()["sources"]:
                    refusals += 1
                else:
                    failures.append(f"unexpected source: {question}")

    return {
        "fixtureVersion": fixture["version"],
        "scope": fixture["note"],
        "hitAt1Page": {"passed": correct_pages, "total": len(fixture["answerable"])},
        "noEvidence": {"passed": refusals, "total": len(fixture["unanswerable"])},
        "failures": failures,
    }


if __name__ == "__main__":
    print(json.dumps(evaluate(), ensure_ascii=False, indent=2))
