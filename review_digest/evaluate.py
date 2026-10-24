"""Сверка разметки модели с ручной эталонной разметкой (data/gold_labels.csv).

Главная метрика для бизнеса — точность и полнота жалоб (пара «отзыв + тема
с негативом»): именно они попадают в топ сводки.
"""
from __future__ import annotations

import csv
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from .models import Review, ReviewLabel
from .taxonomy import TOPIC_KEYS

SIGN = {"+": "positive", "-": "negative", "0": "neutral"}


@dataclass(frozen=True)
class GoldLabel:
    overall: str
    topics: dict[str, str]
    note: str = ""


def load_gold(path: Path) -> dict[str, GoldLabel]:
    gold = {}
    with path.open(encoding="utf-8-sig", newline="") as f:
        for line_no, row in enumerate(csv.DictReader(f), start=2):
            topics = {}
            for part in filter(None, (row["aspects"] or "").split(";")):
                topic, _, sign = part.strip().partition(":")
                if topic not in TOPIC_KEYS or sign not in SIGN:
                    raise ValueError(f"{path.name}:{line_no}: не понимаю «{part}»")
                topics[topic] = SIGN[sign]
            gold[row["review_id"]] = GoldLabel(row["overall"], topics, row.get("note") or "")
    return gold


@dataclass
class PRF:
    tp: int = 0
    fp: int = 0
    fn: int = 0

    @property
    def precision(self) -> float:
        return self.tp / (self.tp + self.fp) if self.tp + self.fp else 1.0

    @property
    def recall(self) -> float:
        return self.tp / (self.tp + self.fn) if self.tp + self.fn else 1.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if p + r else 0.0


@dataclass
class EvalReport:
    total: int = 0
    topics: PRF = field(default_factory=PRF)
    complaints: PRF = field(default_factory=PRF)
    per_topic: dict[str, PRF] = field(default_factory=dict)
    sentiment_matched: int = 0
    sentiment_correct: int = 0
    overall_correct: int = 0
    overall_confusion: Counter = field(default_factory=Counter)
    quotes: int = 0
    quotes_grounded: int = 0
    missing: list[str] = field(default_factory=list)
    errors: list[tuple[Review, GoldLabel, ReviewLabel]] = field(default_factory=list)


def evaluate(
    reviews: list[Review], predicted: dict[str, ReviewLabel], gold: dict[str, GoldLabel]
) -> EvalReport:
    report = EvalReport()
    for review in reviews:
        g = gold.get(review.review_id)
        if g is None:
            continue
        report.total += 1
        p = predicted.get(review.review_id)
        if p is None:
            report.missing.append(review.review_id)
            continue

        pred_topics = p.topics()
        for topic in set(pred_topics) | set(g.topics):
            prf = report.per_topic.setdefault(topic, PRF())
            for target in (report.topics, prf):
                if topic in pred_topics and topic in g.topics:
                    target.tp += 1
                elif topic in pred_topics:
                    target.fp += 1
                else:
                    target.fn += 1
            if topic in pred_topics and topic in g.topics:
                report.sentiment_matched += 1
                report.sentiment_correct += pred_topics[topic] == g.topics[topic]

        pred_neg = {t for t, s in pred_topics.items() if s == "negative"}
        gold_neg = {t for t, s in g.topics.items() if s == "negative"}
        report.complaints.tp += len(pred_neg & gold_neg)
        report.complaints.fp += len(pred_neg - gold_neg)
        report.complaints.fn += len(gold_neg - pred_neg)

        report.overall_correct += p.overall == g.overall
        if p.overall != g.overall:
            report.overall_confusion[(g.overall, p.overall)] += 1

        report.quotes += len(p.aspects)
        report.quotes_grounded += sum(a.grounded for a in p.aspects)

        if pred_topics != g.topics or p.overall != g.overall:
            report.errors.append((review, g, p))
    return report


def _pct(num: float, den: float) -> str:
    return f"{num / den:.0%}" if den else "—"


def _fmt_topics(topics: dict[str, str]) -> str:
    inv = {v: k for k, v in SIGN.items()}
    return ", ".join(f"{t}:{inv[s]}" for t, s in sorted(topics.items())) or "—"


def render_report(report: EvalReport, version: str) -> str:
    r = report
    labeled = r.total - len(r.missing)
    lines = [
        f"# Проверка разметки: `{version}`",
        "",
        f"Отзывов в эталоне: {r.total}, размечено моделью: {labeled}.",
        "",
        "| Метрика | Значение |",
        "|---|---|",
        f"| Жалобы (тема + негатив): точность | {r.complaints.precision:.0%} |",
        f"| Жалобы (тема + негатив): полнота | {r.complaints.recall:.0%} |",
        f"| Темы: точность / полнота / F1 | {r.topics.precision:.0%} / {r.topics.recall:.0%} / {r.topics.f1:.0%} |",
        f"| Тон по совпавшим темам | {_pct(r.sentiment_correct, r.sentiment_matched)} |",
        f"| Общий тон отзыва | {_pct(r.overall_correct, labeled)} |",
        f"| Цитаты, найденные в тексте | {_pct(r.quotes_grounded, r.quotes)} |",
        "",
        "## По темам",
        "",
        "| Тема | Точность | Полнота | TP | FP | FN |",
        "|---|---|---|---|---|---|",
    ]
    for topic in TOPIC_KEYS:
        prf = r.per_topic.get(topic)
        if prf:
            lines.append(
                f"| {topic} | {prf.precision:.0%} | {prf.recall:.0%} | {prf.tp} | {prf.fp} | {prf.fn} |"
            )
    if r.overall_confusion:
        lines += ["", "## Ошибки общего тона (эталон → модель)", ""]
        lines += [f"- {g} → {p}: {n}" for (g, p), n in r.overall_confusion.most_common()]
    if r.missing:
        lines += ["", f"Не размечены: {', '.join(r.missing)}"]
    if r.errors:
        lines += [
            "",
            "## Расхождения",
            "",
            "| id | Отзыв | Эталон | Модель |",
            "|---|---|---|---|",
        ]
        for review, g, p in r.errors:
            text = review.text.replace("|", "/")
            lines.append(
                f"| {review.review_id} | {text} | {g.overall}; {_fmt_topics(g.topics)} "
                f"| {p.overall}; {_fmt_topics(p.topics())} |"
            )
    return "\n".join(lines) + "\n"
