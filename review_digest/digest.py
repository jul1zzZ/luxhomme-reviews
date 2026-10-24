"""Сводка за неделю: счёт по темам, топ жалоб с цитатами, сравнение с прошлой неделей.

Считаем упоминания тем (один отзыв может дать несколько тем), а не отзывы:
«кофе вкусный, но доставка 9 дней» — это и похвала кофе, и жалоба на доставку.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import date, timedelta
from html import escape

from .models import Review, ReviewLabel
from .taxonomy import TOPIC_KEYS, topic_name

# Темы, за которые отвечает не сам товар, а логистика маркетплейса.
NON_PRODUCT_TOPICS = {"delivery", "packaging"}
MAX_COMPLAINTS = 3
QUOTES_PER_COMPLAINT = 2


@dataclass(frozen=True)
class Period:
    start: date
    end: date

    @classmethod
    def week_ending(cls, end: date) -> "Period":
        return cls(end - timedelta(days=6), end)

    def previous(self) -> "Period":
        return Period.week_ending(self.start - timedelta(days=1))

    def label(self) -> str:
        months = "янв фев мар апр мая июн июл авг сен окт ноя дек".split()
        if self.start.month == self.end.month:
            return f"{self.start.day}–{self.end.day} {months[self.end.month - 1]}"
        return (
            f"{self.start.day} {months[self.start.month - 1]} – "
            f"{self.end.day} {months[self.end.month - 1]}"
        )


@dataclass
class WeekStats:
    reviews: int = 0
    unlabeled: int = 0
    avg_rating: float | None = None
    overall: Counter = field(default_factory=Counter)
    mentions: Counter = field(default_factory=Counter)
    negative: Counter = field(default_factory=Counter)
    positive: Counter = field(default_factory=Counter)


@dataclass(frozen=True)
class Quote:
    text: str
    sku: str
    rating: int


@dataclass(frozen=True)
class Complaint:
    topic: str
    count: int
    prev_count: int
    skus: tuple[tuple[str, int], ...]
    quotes: tuple[Quote, ...]


@dataclass
class Digest:
    period: Period
    current: WeekStats
    previous: WeekStats
    complaints: list[Complaint]
    changes: list[str]
    insights: list[str]


def week_stats(reviews: list[Review], labels: dict[str, ReviewLabel]) -> WeekStats:
    stats = WeekStats(reviews=len(reviews))
    if reviews:
        stats.avg_rating = sum(r.rating for r in reviews) / len(reviews)
    for r in reviews:
        label = labels.get(r.review_id)
        if label is None:
            stats.unlabeled += 1
            continue
        stats.overall[label.overall] += 1
        for a in label.aspects:
            stats.mentions[a.topic] += 1
            if a.sentiment == "negative":
                stats.negative[a.topic] += 1
            elif a.sentiment == "positive":
                stats.positive[a.topic] += 1
    return stats


def build_digest(
    period: Period,
    current: list[Review],
    previous: list[Review],
    labels: dict[str, ReviewLabel],
) -> Digest:
    cur = week_stats(current, labels)
    prev = week_stats(previous, labels)
    return Digest(
        period=period,
        current=cur,
        previous=prev,
        complaints=_top_complaints(current, labels, prev),
        changes=_changes(cur, prev),
        insights=_insights(current, labels),
    )


def _top_complaints(
    reviews: list[Review], labels: dict[str, ReviewLabel], prev: WeekStats
) -> list[Complaint]:
    by_topic: dict[str, list[tuple[Review, str, bool]]] = {}
    for r in reviews:
        label = labels.get(r.review_id)
        for a in label.aspects if label else ():
            if a.sentiment == "negative":
                by_topic.setdefault(a.topic, []).append((r, a.quote, a.grounded))

    complaints = []
    for topic, items in by_topic.items():
        skus = Counter(r.sku for r, _, _ in items).most_common()
        # Сначала самые резкие отзывы, по одной цитате на SKU, если получается.
        quotes: list[Quote] = []
        used_skus: set[str] = set()
        for r, quote, grounded in sorted(items, key=lambda x: x[0].rating):
            if not grounded or r.sku in used_skus:
                continue
            quotes.append(Quote(quote, r.sku, r.rating))
            used_skus.add(r.sku)
            if len(quotes) == QUOTES_PER_COMPLAINT:
                break
        complaints.append(
            Complaint(topic, len(items), prev.negative[topic], tuple(skus), tuple(quotes))
        )
    complaints.sort(key=lambda c: (-c.count, -(c.count - c.prev_count), c.topic))
    return complaints[:MAX_COMPLAINTS]


def _changes(cur: WeekStats, prev: WeekStats) -> list[str]:
    # Сначала то, что выросло сильнее всего: команде важнее новые проблемы, чем ушедшие.
    ranked: list[tuple[int, str]] = []
    for topic in TOPIC_KEYS:
        now, before = cur.negative[topic], prev.negative[topic]
        name = topic_name(topic)
        if before == 0 and now >= 2:
            ranked.append((now, f"🆕 {name}: {now} {_complaints(now)}, неделей раньше не было"))
        elif before and now >= 2 * before and now - before >= 2:
            ranked.append((now - before, f"📈 {name}: {now} {_complaints(now)} (было {before})"))
        elif before - now >= 2 and now <= before / 2:
            ranked.append((now - before, f"📉 {name}: {now} {_complaints(now)} (было {before})"))
    changes = [text for _, text in sorted(ranked, key=lambda x: -x[0])]

    if cur.avg_rating is not None and prev.avg_rating is not None:
        delta = cur.avg_rating - prev.avg_rating
        if abs(delta) >= 0.3:
            arrow = "📉" if delta < 0 else "📈"
            changes.append(
                f"{arrow} Средняя оценка {cur.avg_rating:.1f} (было {prev.avg_rating:.1f})"
            )
    return changes


def _insights(reviews: list[Review], labels: dict[str, ReviewLabel]) -> list[str]:
    insights = []

    # 1. Низкие оценки, в которых товар ни при чём — их снижает логистика.
    logistics_only = []
    for r in reviews:
        label = labels.get(r.review_id)
        if not label or r.rating > 3:
            continue
        negative = {a.topic for a in label.aspects if a.sentiment == "negative"}
        if negative and negative <= NON_PRODUCT_TOPICS:
            logistics_only.append(r)
    if logistics_only:
        skus = ", ".join(sorted({r.sku for r in logistics_only}))
        n = len(logistics_only)
        insights.append(
            f"{n} {_plural(n, 'оценка', 'оценки', 'оценок')} ★1–3 ставят из‑за доставки "
            f"или упаковки, а не товара ({skus}). Это вопрос к логистике, а не к продукту"
        )

    # 2. Главная проблема по каждому SKU.
    per_sku: dict[str, Counter] = {}
    for r in reviews:
        label = labels.get(r.review_id)
        for a in label.aspects if label else ():
            if a.sentiment == "negative" and a.topic not in NON_PRODUCT_TOPICS:
                per_sku.setdefault(r.sku, Counter())[a.topic] += 1
    for sku, counter in sorted(per_sku.items()):
        topic, n = counter.most_common(1)[0]
        if n >= 2:
            insights.append(f"{sku}: главная претензия к товару — {topic_name(topic).lower()} ({n})")

    # 3. Оценка не совпадает с текстом — стоит проверить руками.
    mismatched = [
        r.review_id
        for r in reviews
        if (label := labels.get(r.review_id))
        and (
            (r.rating >= 4 and label.overall == "negative")
            or (r.rating <= 2 and label.overall == "positive")
        )
    ]
    if mismatched:
        insights.append(f"Оценка расходится с текстом: {', '.join(mismatched)} — проверить вручную")

    # 4. Темы вне справочника.
    other = sum(
        1
        for r in reviews
        if (label := labels.get(r.review_id)) and "other" in label.topics()
    )
    if other:
        insights.append(f"{other} {_plural(other, 'отзыв', 'отзыва', 'отзывов')} не легли в справочник тем — посмотреть, не появилась ли новая тема")
    return insights


def render_telegram(d: Digest) -> str:
    cur, prev = d.current, d.previous
    lines = [f"<b>📊 Отзывы за {d.period.label()}</b>"]

    rating = f"★ {cur.avg_rating:.1f}" if cur.avg_rating is not None else "★ —"
    if prev.avg_rating is not None:
        rating += f" (было {prev.avg_rating:.1f})"
    lines.append(f"{cur.reviews} {_plural(cur.reviews, 'отзыв', 'отзыва', 'отзывов')} (было {prev.reviews}) · {rating}")
    tone = cur.overall
    lines.append(
        f"👍 {tone['positive']} · 👎 {tone['negative']} · ⚖️ {tone['mixed']} · 😐 {tone['neutral']}"
    )
    if cur.unlabeled:
        lines.append(f"⚠️ Не разобрано: {cur.unlabeled} — см. лог")

    if d.changes:
        lines += ["", "<b>Что изменилось</b>"]
        lines += [escape(c) for c in d.changes]

    if d.complaints:
        lines += ["", "<b>🔥 Топ жалоб</b>"]
        for i, c in enumerate(d.complaints, 1):
            skus = ", ".join(f"{sku} ×{n}" if n > 1 else sku for sku, n in c.skus)
            lines.append(f"{i}. <b>{escape(topic_name(c.topic))}</b> — {c.count} ({escape(skus)})")
            for q in c.quotes:
                lines.append(f"   <i>«{escape(q.text)}»</i> — {q.sku}, ★{q.rating}")

    lines += ["", "<b>По темам</b> <i>(упоминаний, из них 👎; к прошлой неделе)</i>"]
    for topic in sorted(TOPIC_KEYS, key=lambda t: (-cur.mentions[t], t)):
        n = cur.mentions[topic]
        if not n and not prev.mentions[topic]:
            continue
        delta = n - prev.mentions[topic]
        sign = f"+{delta}" if delta > 0 else str(delta) if delta else "±0"
        neg = f", 👎 {cur.negative[topic]}" if cur.negative[topic] else ""
        lines.append(f"• {escape(topic_name(topic))}: {n}{neg} ({sign})")

    # «Общее впечатление» без конкретики продукту ничего не говорит.
    praised = [(t, n) for t, n in cur.positive.most_common() if n >= 2 and t != "general"][:3]
    if praised:
        lines += ["", "<b>👍 Хвалят</b>"]
        lines.append(", ".join(f"{escape(topic_name(t)).lower()} ({n})" for t, n in praised))

    if d.insights:
        lines += ["", "<b>💡 Обратить внимание</b>"]
        lines += [f"• {escape(i)}" for i in d.insights]
    return "\n".join(lines)


def _plural(n: int, one: str, few: str, many: str) -> str:
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


def _complaints(n: int) -> str:
    return _plural(n, "жалоба", "жалобы", "жалоб")
