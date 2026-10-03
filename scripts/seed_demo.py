"""Add the reviewed 2024 public-guide excerpts to a chosen SQLite database.

Usage: python -m scripts.seed_demo --db backend/data/competition-demo.sqlite3
The command is idempotent and never removes other documents.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from backend.app.main import _chunks, _db_connection, _initialize_database


DATASET_PATH = Path(__file__).resolve().parents[1] / "demo" / "guide_excerpts.json"


def seed(database_path: Path) -> tuple[int, int]:
    dataset = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
    _initialize_database(database_path)
    inserted = 0
    skipped = 0
    with _db_connection(database_path) as connection:
        for document in dataset["documents"]:
            document_id = document["id"]
            title = document["title"]
            content = document["content"]
            page = int(document["page"])
            pages_json = json.dumps([{"page": page, "content": content}], ensure_ascii=False)
            existing = connection.execute(
                "SELECT title, content, pages_json FROM documents WHERE id = ?",
                (document_id,),
            ).fetchone()
            if existing is not None:
                if (existing["title"], existing["content"], existing["pages_json"]) != (
                    title, content, pages_json
                ):
                    raise ValueError(
                        f"Demo document {document_id} already exists with different content"
                    )
                skipped += 1
                continue
            connection.execute(
                "INSERT INTO documents (id, title, characters, content, pages_json) "
                "VALUES (?, ?, ?, ?, ?)",
                (document_id, title, len(content), content, pages_json),
            )
            connection.executemany(
                "INSERT INTO chunks (document_id, position, content, page) "
                "VALUES (?, ?, ?, ?)",
                [
                    (document_id, position, chunk, page)
                    for position, chunk in enumerate(_chunks(content))
                ],
            )
            inserted += 1
    return inserted, skipped


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True, type=Path, help="SQLite database path")
    args = parser.parse_args()
    inserted, skipped = seed(args.db)
    print(f"Demo excerpts: {inserted} inserted, {skipped} already present in {args.db}")


if __name__ == "__main__":
    main()
