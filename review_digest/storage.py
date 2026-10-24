"""SQLite-хранилище: отзывы, разметка и отправленные сводки.

Разметка хранится с версией «модель|промпт». Смена модели или промпта не
затирает старые результаты, а размечает отзывы заново — так версии можно
сравнить между собой на эталоне.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path

from .models import Aspect, Review, ReviewLabel

SCHEMA = """
CREATE TABLE IF NOT EXISTS reviews (
    review_id TEXT PRIMARY KEY,
    date      TEXT NOT NULL,
    sku       TEXT NOT NULL,
    rating    INTEGER NOT NULL,
    text      TEXT NOT NULL,
    source    TEXT NOT NULL,
    loaded_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS reviews_date ON reviews(date);
CREATE TABLE IF NOT EXISTS labels (
    review_id     TEXT NOT NULL REFERENCES reviews(review_id),
    label_version TEXT NOT NULL,
    overall       TEXT NOT NULL,
    aspects_json  TEXT NOT NULL,
    labeled_at    TEXT NOT NULL,
    PRIMARY KEY (review_id, label_version)
);
CREATE TABLE IF NOT EXISTS digests (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    period_start  TEXT NOT NULL,
    period_end    TEXT NOT NULL,
    label_version TEXT NOT NULL,
    text          TEXT NOT NULL,
    sent_at       TEXT NOT NULL
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(path)
        self._db.row_factory = sqlite3.Row
        self._db.executescript(SCHEMA)

    def close(self) -> None:
        self._db.close()

    def __enter__(self) -> "Store":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def add_reviews(self, reviews: list[Review]) -> int:
        """Добавляет новые отзывы, уже известные пропускает. Возвращает число новых."""
        before = self._db.total_changes
        with self._db:
            self._db.executemany(
                "INSERT OR IGNORE INTO reviews VALUES (?, ?, ?, ?, ?, ?, ?)",
                [
                    (r.review_id, r.date.isoformat(), r.sku, r.rating, r.text, r.source, _now())
                    for r in reviews
                ],
            )
        return self._db.total_changes - before

    def reviews_between(self, start: date, end: date) -> list[Review]:
        rows = self._db.execute(
            "SELECT * FROM reviews WHERE date BETWEEN ? AND ? ORDER BY date, review_id",
            (start.isoformat(), end.isoformat()),
        )
        return [_row_to_review(r) for r in rows]

    def all_reviews(self) -> list[Review]:
        rows = self._db.execute("SELECT * FROM reviews ORDER BY date, review_id")
        return [_row_to_review(r) for r in rows]

    def latest_date(self) -> date | None:
        row = self._db.execute("SELECT MAX(date) FROM reviews").fetchone()
        return date.fromisoformat(row[0]) if row[0] else None

    def unlabeled(self, version: str) -> list[Review]:
        rows = self._db.execute(
            """SELECT r.* FROM reviews r
               LEFT JOIN labels l ON l.review_id = r.review_id AND l.label_version = ?
               WHERE l.review_id IS NULL ORDER BY r.date, r.review_id""",
            (version,),
        )
        return [_row_to_review(r) for r in rows]

    def save_labels(self, version: str, labels: list[ReviewLabel]) -> None:
        with self._db:
            self._db.executemany(
                "INSERT OR REPLACE INTO labels VALUES (?, ?, ?, ?, ?)",
                [
                    (
                        label.review_id,
                        version,
                        label.overall,
                        json.dumps(
                            [a.__dict__ for a in label.aspects], ensure_ascii=False
                        ),
                        _now(),
                    )
                    for label in labels
                ],
            )

    def labels(self, version: str) -> dict[str, ReviewLabel]:
        rows = self._db.execute(
            "SELECT review_id, overall, aspects_json FROM labels WHERE label_version = ?",
            (version,),
        )
        return {
            r["review_id"]: ReviewLabel(
                review_id=r["review_id"],
                overall=r["overall"],
                aspects=tuple(Aspect(**a) for a in json.loads(r["aspects_json"])),
            )
            for r in rows
        }

    def save_digest(self, start: date, end: date, version: str, text: str) -> None:
        with self._db:
            self._db.execute(
                "INSERT INTO digests (period_start, period_end, label_version, text, sent_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (start.isoformat(), end.isoformat(), version, text, _now()),
            )


def _row_to_review(row: sqlite3.Row) -> Review:
    return Review(
        review_id=row["review_id"],
        date=date.fromisoformat(row["date"]),
        sku=row["sku"],
        rating=row["rating"],
        text=row["text"],
        source=row["source"],
    )
