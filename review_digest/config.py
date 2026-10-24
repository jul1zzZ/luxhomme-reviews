from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MODEL = "gemini-3.6-flash"


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class Settings:
    gemini_api_key: str | None
    gemini_model: str
    telegram_token: str | None
    telegram_chat_id: str | None
    db_path: Path
    batch_size: int

    def require_gemini(self) -> str:
        if not self.gemini_api_key:
            raise ConfigError("Не задан GEMINI_API_KEY — добавьте его в .env (см. .env.example)")
        return self.gemini_api_key

    def require_telegram(self) -> tuple[str, str]:
        if not self.telegram_token or not self.telegram_chat_id:
            raise ConfigError(
                "Не заданы TELEGRAM_BOT_TOKEN и/или TELEGRAM_CHAT_ID — добавьте их в .env "
                "или запустите с --dry-run"
            )
        return self.telegram_token, self.telegram_chat_id


def load_settings() -> Settings:
    load_dotenv(ROOT / ".env")
    db_path = Path(os.getenv("DB_PATH", "data/reviews.db"))
    if not db_path.is_absolute():
        db_path = ROOT / db_path
    try:
        batch_size = int(os.getenv("BATCH_SIZE", "15"))
    except ValueError as exc:
        raise ConfigError("BATCH_SIZE должен быть числом") from exc
    return Settings(
        gemini_api_key=os.getenv("GEMINI_API_KEY") or None,
        gemini_model=os.getenv("GEMINI_MODEL") or DEFAULT_MODEL,
        telegram_token=os.getenv("TELEGRAM_BOT_TOKEN") or None,
        telegram_chat_id=os.getenv("TELEGRAM_CHAT_ID") or None,
        db_path=db_path,
        batch_size=max(1, batch_size),
    )
