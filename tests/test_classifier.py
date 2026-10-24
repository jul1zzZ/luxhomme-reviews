import json
from datetime import date
from types import SimpleNamespace

from review_digest.classifier import GeminiClassifier, is_grounded, parse_response
from review_digest.models import Review

R1 = Review("r1", date(2026, 10, 8), "CM-2010", 4, "Кофе вкусный, но доставка 9 дней")
R2 = Review("r2", date(2026, 10, 8), "RV-0707", 2, "Застревает под диваном, шумит")


def test_grounding_tolerates_case_and_yo():
    assert is_grounded("кофе вкусный", R1.text)
    assert is_grounded("«Доставка 9 дней».", R1.text)
    assert is_grounded("пришел", "Пришёл с трещиной")
    assert not is_grounded("доставка 3 дня", R1.text)
    assert not is_grounded("", R1.text)


def test_parse_response_validates_everything():
    raw = json.dumps(
        [
            {
                "review_id": "r1",
                "overall": "mixed",
                "aspects": [
                    {"topic": "performance", "sentiment": "positive", "quote": "Кофе вкусный"},
                    {"topic": "delivery", "sentiment": "negative", "quote": "долго везли"},
                    {"topic": "delivery", "sentiment": "negative", "quote": "доставка 9 дней"},
                    {"topic": "smell", "sentiment": "negative", "quote": "Кофе"},
                ],
            },
            {"review_id": "r999", "overall": "positive", "aspects": []},
        ]
    )
    labels, problems = parse_response(raw, [R1, R2])
    assert len(labels) == 1
    aspects = labels[0].aspects
    assert [a.topic for a in aspects] == ["performance", "delivery"]
    assert aspects[1].grounded is False  # выдуманная цитата помечена
    assert any("r999" in p for p in problems)
    assert any("smell" in p for p in problems)


class FakeModels:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def generate_content(self, model, contents, config):
        self.calls.append(contents)
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return SimpleNamespace(text=item)


def make(responses):
    models = FakeModels(responses)
    clf = GeminiClassifier(SimpleNamespace(models=models), "test-model", sleep=lambda s: None)
    return clf, models


def label(rid):
    return {"review_id": rid, "overall": "negative", "aspects": []}


def test_retries_then_reasks_missing_review():
    clf, models = make(
        [
            RuntimeError("503"),
            "not json",
            json.dumps([label("r1")]),  # r2 потерялся
            json.dumps([label("r2")]),  # переспросили r2 отдельно
        ]
    )
    labels, problems = clf.classify([R1, R2])
    assert {l.review_id for l in labels} == {"r1", "r2"}
    assert len(models.calls) == 4
    assert '"r2"' in models.calls[-1] and '"r1"' not in models.calls[-1]
    assert not problems


def test_gives_up_after_retries():
    clf, _ = make([RuntimeError("quota")] * 6)
    labels, problems = clf.classify([R1])
    assert labels == []
    assert any("не удалось разметить" in p for p in problems)


def test_prompt_contains_text_but_not_rating():
    clf, models = make([json.dumps([label("r1")])])
    clf.classify([R1])
    prompt = models.calls[0]
    assert R1.text in prompt and "delivery" in prompt
    assert '"rating"' not in prompt
