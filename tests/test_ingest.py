from datetime import date

import pytest

from review_digest.ingest import IngestError, load_csv, parse_date


def test_sample_file_loads(reviews):
    assert len(reviews) == 48
    assert reviews[2].text == "Кофе вкусный, но доставка 9 дней"
    assert reviews[2].date == date(2026, 10, 12)


@pytest.mark.parametrize(
    "raw, expected",
    [("2026-10-06", date(2026, 10, 6)), ("06.10.2026", date(2026, 10, 6)), ("06.10", date(2025, 10, 6))],
)
def test_parse_date(raw, expected):
    assert parse_date(raw, default_year=2025) == expected


def test_semicolon_csv_with_bad_rows(tmp_path):
    path = tmp_path / "excel.csv"
    path.write_text(
        "DATE;SKU;RATING;TEXT\n"
        "06.10;af-5501;5;Готовит быстро\n"
        "07.10;RV-0707;7;Слишком хорошо\n"
        "08.10;CM-2010;4;\n"
        "06.10;af-5501;5;Готовит быстро\n"
        "вчера;CM-2010;4;Кофе вкусный\n",
        encoding="utf-8-sig",
    )
    reviews, warnings = load_csv(path, default_year=2026)
    assert [r.sku for r in reviews] == ["AF-5501"]
    assert len(warnings) == 4
    assert any("вне диапазона" in w for w in warnings)
    assert any("дубликат" in w for w in warnings)


def test_missing_columns(tmp_path):
    path = tmp_path / "bad.csv"
    path.write_text("date,text\n2026-10-06,ok\n", encoding="utf-8")
    with pytest.raises(IngestError, match="rating"):
        load_csv(path)
