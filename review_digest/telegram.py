from __future__ import annotations

import logging
import time

import requests

log = logging.getLogger(__name__)

API_URL = "https://api.telegram.org/bot{token}/sendMessage"
MAX_LENGTH = 4096


class TelegramError(Exception):
    pass


def split_message(text: str, limit: int = MAX_LENGTH) -> list[str]:
    """Режет длинную сводку по строкам, чтобы не разорвать HTML-тег посередине."""
    chunks, current = [], ""
    for line in text.split("\n"):
        candidate = f"{current}\n{line}" if current else line
        if len(candidate) <= limit:
            current = candidate
            continue
        if current:
            chunks.append(current)
        while len(line) > limit:  # одна гигантская строка — режем как есть
            chunks.append(line[:limit])
            line = line[limit:]
        current = line
    if current:
        chunks.append(current)
    return chunks


def send_message(
    token: str,
    chat_id: str,
    text: str,
    session: requests.Session | None = None,
    timeout: float = 15,
) -> None:
    http = session or requests.Session()
    url = API_URL.format(token=token)
    for chunk in split_message(text):
        _send_chunk(http, url, chat_id, chunk, timeout)


def _send_chunk(http, url: str, chat_id: str, text: str, timeout: float, attempts: int = 3) -> None:
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    for attempt in range(1, attempts + 1):
        try:
            resp = http.post(url, json=payload, timeout=timeout)
        except requests.RequestException as exc:
            # В тексте исключения requests есть URL с токеном — наружу его не отдаём.
            error = f"сеть недоступна ({type(exc).__name__})"
        else:
            try:
                body = resp.json()
            except ValueError:
                body = {}
            if body.get("ok"):
                return
            error = f"{resp.status_code}: {body.get('description', 'неизвестная ошибка')}"
            if resp.status_code == 429:
                wait = body.get("parameters", {}).get("retry_after", 5)
                log.warning("Telegram просит подождать %s с", wait)
                time.sleep(wait)
                continue
            if resp.status_code < 500:
                raise TelegramError(error)  # 400/401/403 повтором не исправить
        log.warning("Telegram, попытка %d/%d: %s", attempt, attempts, error)
        if attempt < attempts:
            time.sleep(2**attempt)
    raise TelegramError(error)
