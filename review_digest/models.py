from __future__ import annotations

from dataclasses import dataclass
from datetime import date

SENTIMENTS = ("positive", "negative", "neutral")
OVERALL = ("positive", "negative", "neutral", "mixed")


@dataclass(frozen=True)
class Review:
    review_id: str
    date: date
    sku: str
    rating: int
    text: str
    source: str = "csv"


@dataclass(frozen=True)
class Aspect:
    topic: str
    sentiment: str
    quote: str
    # True, если цитата действительно найдена в тексте отзыва.
    # Неподтверждённые цитаты в сводку не попадают.
    grounded: bool = True


@dataclass(frozen=True)
class ReviewLabel:
    review_id: str
    overall: str
    aspects: tuple[Aspect, ...]

    def topics(self) -> dict[str, str]:
        return {a.topic: a.sentiment for a in self.aspects}
