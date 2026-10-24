from datetime import date

from review_digest.digest import Period, build_digest, render_telegram


def make_digest(reviews, labels):
    period = Period.week_ending(date(2026, 10, 24))
    prev = period.previous()
    in_period = lambda p: [r for r in reviews if p.start <= r.date <= p.end]
    return build_digest(period, in_period(period), in_period(prev), labels)


def test_periods():
    period = Period.week_ending(date(2026, 10, 24))
    assert period.start == date(2026, 10, 18)
    assert period.previous() == Period(date(2026, 10, 11), date(2026, 10, 17))
    assert period.label() == "18–24 окт"


def test_counts_and_changes(reviews, gold_as_labels):
    d = make_digest(reviews, gold_as_labels)
    assert d.current.reviews == 28 and d.previous.reviews == 20
    assert d.current.negative["delivery"] == 7
    assert d.previous.negative["delivery"] == 1

    top = d.complaints[0]
    assert top.topic == "delivery" and top.count == 7 and top.prev_count == 1
    assert d.complaints[1].topic == "app_connectivity"
    assert len(top.quotes) == 2
    assert top.quotes[0].rating == 1  # самый резкий отзыв первым

    changes = "\n".join(d.changes)
    assert "Доставка: 7 жалоб (было 1)" in changes
    assert "Приложение и прошивка: 6 жалоб, неделей раньше не было" in changes
    assert "Шум" in changes  # шума стало меньше


def test_insights(reviews, gold_as_labels):
    insights = "\n".join(make_digest(reviews, gold_as_labels).insights)
    assert "из‑за доставки" in insights
    assert "RV-0707: главная претензия к товару — приложение и прошивка" in insights


def test_render_escapes_html_and_handles_unlabeled(reviews, gold_as_labels):
    labels = dict(gold_as_labels)
    del labels["r048"]
    text = render_telegram(make_digest(reviews, labels))
    assert text.startswith("<b>📊 Отзывы за 18–24 окт</b>")
    assert "Не разобрано: 1" in text
    assert "<script>" not in text


def test_empty_week():
    period = Period.week_ending(date(2026, 1, 7))
    text = render_telegram(build_digest(period, [], [], {}))
    assert "0 отзывов" in text
