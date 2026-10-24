from pathlib import Path

import pytest

from review_digest.evaluate import load_gold
from review_digest.ingest import load_csv
from review_digest.models import Aspect, ReviewLabel

DATA = Path(__file__).resolve().parent.parent / "data"


@pytest.fixture(scope="session")
def reviews():
    reviews, warnings = load_csv(DATA / "reviews.csv")
    assert not warnings
    return reviews


@pytest.fixture(scope="session")
def gold():
    return load_gold(DATA / "gold_labels.csv")


@pytest.fixture(scope="session")
def gold_as_labels(reviews, gold):
    """Эталон в виде предсказаний модели — для проверки сводки без обращения к LLM."""
    by_id = {r.review_id: r for r in reviews}
    return {
        rid: ReviewLabel(
            rid,
            g.overall,
            tuple(Aspect(t, s, by_id[rid].text[:20], True) for t, s in g.topics.items()),
        )
        for rid, g in gold.items()
    }
