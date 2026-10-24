"""Разметка отзывов по темам и тону через Gemini.

Модели отдаём пачку отзывов и JSON-схему ответа. Ответу при этом не верим
на слово: каждую запись проверяем (известный ли review_id, тема из
справочника, есть ли цитата в тексте отзыва). Отзывы, которые модель
пропустила, переспрашиваем по одному.
"""
from __future__ import annotations

import json
import logging
import re
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .config import ROOT
from .models import OVERALL, SENTIMENTS, Aspect, Review, ReviewLabel
from .taxonomy import TOPIC_KEYS, taxonomy_for_prompt

log = logging.getLogger(__name__)

PROMPT_VERSION = "v2"
PROMPT_PATH = ROOT / "prompts" / f"classify_{PROMPT_VERSION}.md"

RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "review_id": {"type": "string"},
            "overall": {"type": "string", "enum": list(OVERALL)},
            "aspects": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "topic": {"type": "string", "enum": list(TOPIC_KEYS)},
                        "sentiment": {"type": "string", "enum": list(SENTIMENTS)},
                        "quote": {"type": "string"},
                    },
                    "required": ["topic", "sentiment", "quote"],
                },
            },
        },
        "required": ["review_id", "overall", "aspects"],
    },
}


class ClassifierError(Exception):
    pass


def build_prompt(reviews: list[Review], template: str) -> str:
    payload = [{"review_id": r.review_id, "text": r.text} for r in reviews]
    return template.replace("{{TAXONOMY}}", taxonomy_for_prompt()).replace(
        "{{REVIEWS}}", json.dumps(payload, ensure_ascii=False, indent=1)
    )


def _normalize(text: str) -> str:
    text = text.lower().replace("ё", "е")
    text = re.sub(r"[«»\"'“”„]", "", text)
    return " ".join(text.split())


def is_grounded(quote: str, text: str) -> bool:
    quote = _normalize(quote).strip(" .,!?…—-")
    return bool(quote) and quote in _normalize(text)


def parse_response(raw: str, batch: list[Review]) -> tuple[list[ReviewLabel], list[str]]:
    """Разбирает ответ модели. Возвращает валидные метки и список замечаний."""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ClassifierError(f"модель вернула не JSON: {exc}") from exc
    if not isinstance(data, list):
        raise ClassifierError("модель вернула не список")

    by_id = {r.review_id: r for r in batch}
    labels: dict[str, ReviewLabel] = {}
    problems: list[str] = []
    for item in data:
        if not isinstance(item, dict):
            problems.append("элемент ответа не объект")
            continue
        rid = str(item.get("review_id", ""))
        review = by_id.get(rid)
        if review is None:
            problems.append(f"неизвестный review_id {rid!r}")
            continue
        if rid in labels:
            problems.append(f"{rid}: повтор в ответе")
            continue
        overall = item.get("overall")
        if overall not in OVERALL:
            problems.append(f"{rid}: недопустимый overall {overall!r}")
            continue

        aspects: list[Aspect] = []
        seen: set[str] = set()
        for a in item.get("aspects") or []:
            topic, sentiment = a.get("topic"), a.get("sentiment")
            quote = str(a.get("quote") or "").strip()
            if topic not in TOPIC_KEYS:
                problems.append(f"{rid}: неизвестная тема {topic!r}")
                continue
            if sentiment not in SENTIMENTS:
                problems.append(f"{rid}: недопустимый тон {sentiment!r} для {topic}")
                continue
            if topic in seen:
                continue
            seen.add(topic)
            grounded = is_grounded(quote, review.text)
            if not grounded:
                problems.append(f"{rid}: цитата не найдена в отзыве: {quote!r}")
            aspects.append(Aspect(topic, sentiment, quote, grounded))
        labels[rid] = ReviewLabel(rid, overall, tuple(aspects))
    return list(labels.values()), problems


class GeminiClassifier:
    def __init__(
        self,
        client: Any,
        model: str,
        batch_size: int = 15,
        max_retries: int = 3,
        prompt_path: Path = PROMPT_PATH,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self._client = client
        self._model = model
        self._batch_size = batch_size
        self._max_retries = max_retries
        self._template = prompt_path.read_text(encoding="utf-8")
        self._sleep = sleep

    @property
    def version(self) -> str:
        return f"{self._model}|{PROMPT_VERSION}"

    def classify(self, reviews: list[Review]) -> tuple[list[ReviewLabel], list[str]]:
        labels: list[ReviewLabel] = []
        problems: list[str] = []
        for start in range(0, len(reviews), self._batch_size):
            batch = reviews[start : start + self._batch_size]
            log.info("Размечаю отзывы %d–%d из %d", start + 1, start + len(batch), len(reviews))
            got, issues = self._classify_batch(batch)
            problems += issues

            missing = [r for r in batch if r.review_id not in {l.review_id for l in got}]
            for review in missing:
                # Модель пропустила отзыв в пачке — переспрашиваем его отдельно.
                log.warning("%s пропущен в ответе, переспрашиваю отдельно", review.review_id)
                single, issues = self._classify_batch([review])
                got += single
                problems += issues
                if not single:
                    problems.append(f"{review.review_id}: не удалось разметить")
            labels += got
        return labels, problems

    def _classify_batch(self, batch: list[Review]) -> tuple[list[ReviewLabel], list[str]]:
        prompt = build_prompt(batch, self._template)
        last_error: Exception | None = None
        for attempt in range(1, self._max_retries + 1):
            try:
                return parse_response(self._call(prompt), batch)
            except Exception as exc:  # сеть, квоты, невалидный JSON — всё лечится повтором
                last_error = exc
                log.warning("Попытка %d/%d не удалась: %s", attempt, self._max_retries, exc)
                if attempt < self._max_retries:
                    self._sleep(2**attempt)
        ids = ", ".join(r.review_id for r in batch)
        return [], [f"пачка [{ids}] не размечена: {last_error}"]

    def _call(self, prompt: str) -> str:
        from google.genai import types

        response = self._client.models.generate_content(
            model=self._model,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_json_schema=RESPONSE_SCHEMA,
            ),
        )
        if not response.text:
            raise ClassifierError("пустой ответ модели")
        return response.text


def make_classifier(api_key: str, model: str, batch_size: int) -> GeminiClassifier:
    from google import genai

    return GeminiClassifier(genai.Client(api_key=api_key), model, batch_size)
