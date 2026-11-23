"""Application configuration loaded from .env file."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import List, Tuple

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


BASE_DIR = Path(__file__).resolve().parent


def _parse_id_name_entries(raw: str) -> List[Tuple[int, str]]:
    """Parse comma-separated Telegram user entries like '5649321700:Asad, 12345' into (id, label)."""
    result: List[Tuple[int, str]] = []
    seen: set[int] = set()
    for item in raw.split(","):
        cleaned = item.strip()
        if not cleaned:
            continue
        if ":" in cleaned:
            id_part, label_part = cleaned.split(":", maxsplit=1)
            id_part = id_part.strip()
            label = label_part.strip()
        else:
            id_part = cleaned
            label = ""
        if id_part.lstrip("-").isdigit():
            val = int(id_part)
            if val not in seen:
                seen.add(val)
                result.append((val, label))
    return result


def _parse_int_list(raw: str) -> List[int]:
    """Parse comma-separated Telegram user IDs (with optional :Name labels) into a list of ints."""
    return [uid for uid, _ in _parse_id_name_entries(raw)]


class Settings(BaseSettings):
    """Typed environment settings for Norin AI Hisobot Bot."""

    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    BOT_TOKEN: str = "YOUR_TELEGRAM_BOT_TOKEN_HERE"
    SUPER_ADMIN_IDS: str = "5649321700"
    ADMIN_IDS: str = ""
    OWNER_CONTACT: str = "@SunnatDevPy"
    DEFAULT_MONTHLY_PRICE: float = 400000.0
    DEFAULT_TRIAL_DAYS: int = 30

    DATABASE_URL: str = f"sqlite+aiosqlite:///{(BASE_DIR / 'data' / 'norin_bot.db').as_posix()}"

    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-flash-lite-latest"

    TIMEZONE: str = "Asia/Tashkent"

    # Mobile app API (norin-api)
    API_JWT_SECRET: str = ""
    API_PUBLIC_URL: str = "http://46.8.194.206:8000"
    API_ACCESS_TTL_MIN: int = 30
    API_REFRESH_TTL_DAYS: int = 30
    API_OTP_TTL_MIN: int = 5

    @field_validator("DATABASE_URL")
    @classmethod
    def ensure_sqlite_dir(cls, value: str) -> str:
        """Ensure parent directory exists when using a local SQLite database file."""
        if value.startswith("sqlite"):
            db_part = value.split("///", maxsplit=1)[-1]
            if db_part and db_part != ":memory:":
                db_path = Path(db_part)
                if not db_path.is_absolute():
                    db_path = BASE_DIR / db_path
                db_path.parent.mkdir(parents=True, exist_ok=True)
        return value

    @property
    def super_admin_id_list(self) -> List[int]:
        """Parse comma-separated Super Admin (developer/owner) Telegram user IDs."""
        return _parse_int_list(self.SUPER_ADMIN_IDS)

    @property
    def admin_id_list(self) -> List[int]:
        """Parse comma-separated authorized Telegram user IDs from .env."""
        return _parse_int_list(self.ADMIN_IDS)

    @property
    def admin_entries(self) -> List[Tuple[int, str]]:
        """Parse authorized Telegram user IDs with optional labels from .env."""
        return _parse_id_name_entries(self.ADMIN_IDS)

    @property
    def formatted_admin_entries(self) -> str:
        """Render .env ADMIN_IDS cleanly with optional names."""
        entries = self.admin_entries
        if not entries:
            return "yo'q"
        return ", ".join(f"{uid} ({lbl})" if lbl else str(uid) for uid, lbl in entries)


@lru_cache
def get_settings() -> Settings:
    """Return cached Settings instance."""
    return Settings()
