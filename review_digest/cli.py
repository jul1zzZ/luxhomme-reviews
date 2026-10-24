from __future__ import annotations

import argparse
import logging
import sys
from datetime import date
from pathlib import Path

from .classifier import make_classifier
from .config import ROOT, ConfigError, Settings, load_settings
from .digest import Period, build_digest, render_telegram
from .evaluate import evaluate, load_gold, render_report
from .ingest import IngestError, load_csv
from .storage import Store
from .telegram import TelegramError, send_message

log = logging.getLogger("review_digest")


def cmd_load(args, settings: Settings) -> None:
    reviews, warnings = load_csv(Path(args.csv), default_year=args.year)
    for w in warnings:
        log.warning("CSV: %s", w)
    with Store(settings.db_path) as store:
        added = store.add_reviews(reviews)
    log.info("Прочитано %d отзывов, новых в базе: %d", len(reviews), added)


def cmd_classify(args, settings: Settings) -> None:
    classifier = make_classifier(
        settings.require_gemini(), settings.gemini_model, settings.batch_size
    )
    with Store(settings.db_path) as store:
        todo = store.unlabeled(classifier.version)
        if not todo:
            log.info("Все отзывы уже размечены версией %s", classifier.version)
            return
        labels, problems = classifier.classify(todo)
        store.save_labels(classifier.version, labels)
    for p in problems:
        log.warning("Разметка: %s", p)
    log.info("Размечено %d из %d отзывов (%s)", len(labels), len(todo), classifier.version)


def cmd_digest(args, settings: Settings) -> None:
    version = f"{settings.gemini_model}|{_prompt_version()}"
    with Store(settings.db_path) as store:
        end = date.fromisoformat(args.as_of) if args.as_of else store.latest_date()
        if end is None:
            raise ConfigError("В базе нет отзывов — сначала выполните load")
        period = Period.week_ending(end)
        prev = period.previous()
        labels = store.labels(version)
        digest = build_digest(
            period,
            store.reviews_between(period.start, period.end),
            store.reviews_between(prev.start, prev.end),
            labels,
        )
        text = render_telegram(digest)

        if args.dry_run:
            print(text)
            return
        token, chat_id = settings.require_telegram()
        send_message(token, chat_id, text)
        store.save_digest(period.start, period.end, version, text)
    log.info("Сводка за %s отправлена в Telegram", period.label())


def cmd_run(args, settings: Settings) -> None:
    cmd_load(args, settings)
    cmd_classify(args, settings)
    cmd_digest(args, settings)


def cmd_evaluate(args, settings: Settings) -> None:
    version = f"{settings.gemini_model}|{_prompt_version()}"
    gold = load_gold(Path(args.gold))
    with Store(settings.db_path) as store:
        report = evaluate(store.all_reviews(), store.labels(version), gold)
    text = render_report(report, version)
    out = ROOT / "reports" / f"eval_{version.replace('|', '_')}.md"
    out.parent.mkdir(exist_ok=True)
    out.write_text(text, encoding="utf-8")
    print(text)
    log.info("Отчёт сохранён: %s", out.relative_to(ROOT))


def _prompt_version() -> str:
    from .classifier import PROMPT_VERSION

    return PROMPT_VERSION


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m review_digest",
        description="AI-разбор отзывов и еженедельная сводка в Telegram",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="подробный лог")
    sub = parser.add_subparsers(dest="command", required=True)

    def add_csv(p):
        p.add_argument("--csv", default="data/reviews.csv", help="CSV с отзывами")
        p.add_argument("--year", type=int, help="год для дат без года (06.10)")

    def add_digest(p):
        p.add_argument("--as-of", help="последний день недели YYYY-MM-DD (по умолчанию — дата самого свежего отзыва)")
        p.add_argument("--dry-run", action="store_true", help="напечатать сводку, не отправляя")

    p = sub.add_parser("run", help="всё сразу: загрузить → разметить → отправить сводку")
    add_csv(p)
    add_digest(p)
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("load", help="загрузить отзывы из CSV в базу")
    add_csv(p)
    p.set_defaults(func=cmd_load)

    p = sub.add_parser("classify", help="разметить новые отзывы через Gemini")
    p.set_defaults(func=cmd_classify)

    p = sub.add_parser("digest", help="собрать и отправить сводку")
    add_digest(p)
    p.set_defaults(func=cmd_digest)

    p = sub.add_parser("evaluate", help="сверить разметку модели с эталоном")
    p.add_argument("--gold", default="data/gold_labels.csv")
    p.set_defaults(func=cmd_evaluate)
    return parser


def main(argv: list[str] | None = None) -> int:
    # Windows-консоль по умолчанию не в UTF-8, а в сводке кириллица и эмодзи.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )
    # httpx (внутри google-genai) пишет в INFO полный URL запроса — прячем.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    try:
        args.func(args, load_settings())
    except (ConfigError, IngestError, TelegramError, ValueError) as exc:
        log.error("%s", exc)
        return 1
    return 0
