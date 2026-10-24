"""Загрузка отзывов из CSV-выгрузки.

Выгрузки с маркетплейсов и из Excel бывают разными, поэтому парсер терпим:
понимает `,` и `;` как разделитель, BOM, даты `2026-10-06`, `06.10.2026` и `06.10`.
Битые строки не валят загрузку, а попадают в список предупреждений.
"""
from __future__ import annotations

import csv
import hashlib
from datetime import date, datetime
from pathlib import Path

from .models import Review

REQUIRED_COLUMNS = {"date", "sku", "rating", "text"}


class IngestError(Exception):
    pass


def parse_date(raw: str, default_year: int) -> date:
    raw = raw.strip()
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d.%m.%y"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            pass
    try:
        # «06.10» без года, как в примере из задания
        parsed = datetime.strptime(raw, "%d.%m")
    except ValueError:
        raise ValueError(f"не понимаю дату «{raw}»") from None
    return parsed.date().replace(year=default_year)


def make_review_id(day: date, sku: str, text: str) -> str:
    digest = hashlib.sha1(f"{day.isoformat()}|{sku}|{text}".encode()).hexdigest()
    return f"h{digest[:12]}"


def load_csv(path: Path, default_year: int | None = None) -> tuple[list[Review], list[str]]:
    if not path.exists():
        raise IngestError(f"Файл не найден: {path}")
    default_year = default_year or date.today().year

    with path.open(encoding="utf-8-sig", newline="") as f:
        sample = f.read(4096)
        f.seek(0)
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
        except csv.Error:
            dialect = csv.excel
        reader = csv.DictReader(f, dialect=dialect)
        columns = {c.strip().lower() for c in reader.fieldnames or []}
        missing = REQUIRED_COLUMNS - columns
        if missing:
            raise IngestError(f"В CSV нет колонок: {', '.join(sorted(missing))}")

        reviews: dict[str, Review] = {}
        warnings: list[str] = []
        for line_no, row in enumerate(reader, start=2):
            row = {(k or "").strip().lower(): (v or "").strip() for k, v in row.items()}
            try:
                review = _parse_row(row, default_year)
            except ValueError as exc:
                warnings.append(f"строка {line_no}: {exc}")
                continue
            if review.review_id in reviews:
                warnings.append(f"строка {line_no}: дубликат {review.review_id}, пропущен")
                continue
            reviews[review.review_id] = review
    return list(reviews.values()), warnings


def _parse_row(row: dict[str, str], default_year: int) -> Review:
    text = " ".join(row["text"].split())
    if not text:
        raise ValueError("пустой текст")
    sku = row["sku"].upper()
    if not sku:
        raise ValueError("пустой SKU")
    try:
        rating = int(float(row["rating"].replace(",", ".")))
    except ValueError:
        raise ValueError(f"оценка «{row['rating']}» не число") from None
    if not 1 <= rating <= 5:
        raise ValueError(f"оценка {rating} вне диапазона 1–5")
    day = parse_date(row["date"], default_year)
    review_id = row.get("id") or make_review_id(day, sku, text)
    return Review(
        review_id=review_id,
        date=day,
        sku=sku,
        rating=rating,
        text=text,
        source=row.get("source") or "csv",
    )
