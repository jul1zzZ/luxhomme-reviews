from types import SimpleNamespace

import pytest

from review_digest.evaluate import evaluate
from review_digest.telegram import TelegramError, send_message, split_message


def test_split_message_respects_limit():
    text = "\n".join(f"строка {i}" for i in range(100))
    chunks = split_message(text, limit=50)
    assert all(len(c) <= 50 for c in chunks)
    assert "\n".join(chunks) == text


class FakeSession:
    def __init__(self, status, body):
        self.status, self.body, self.posts = status, body, []

    def post(self, url, json, timeout):
        self.posts.append((url, json))
        return SimpleNamespace(status_code=self.status, json=lambda: self.body)


def test_send_ok():
    session = FakeSession(200, {"ok": True})
    send_message("TOKEN", "42", "<b>hi</b>", session=session)
    url, payload = session.posts[0]
    assert "botTOKEN" in url and payload["parse_mode"] == "HTML"


def test_send_error_does_not_leak_token():
    session = FakeSession(400, {"ok": False, "description": "Bad Request: chat not found"})
    with pytest.raises(TelegramError) as exc:
        send_message("SECRET", "42", "hi", session=session)
    assert "chat not found" in str(exc.value)
    assert "SECRET" not in str(exc.value)
    assert len(session.posts) == 1  # 400 не повторяем


def test_evaluate_perfect_predictions(reviews, gold, gold_as_labels):
    report = evaluate(reviews, gold_as_labels, gold)
    assert report.total == 48
    assert report.complaints.precision == report.complaints.recall == 1.0
    assert report.overall_correct == 48
    assert not report.errors
