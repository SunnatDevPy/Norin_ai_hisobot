"""Shared APK version metadata and binary paths for norin-api and norin-bot."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from config import BASE_DIR

APK_BINARY_PATH: Path = BASE_DIR / "data" / "norin_ai.apk"
APK_VERSION_PATH: Path = BASE_DIR / "data" / "apk_version.json"


def get_apk_version_metadata() -> Dict[str, Any]:
    """Return latest uploaded APK version metadata and binary availability."""
    meta: Dict[str, Any] = {
        "version": "1.0.0",
        "build": 1,
        "full": "1.0.0+1",
        "built_at": "",
        "size_bytes": 0,
        "apk_available": False,
    }
    if APK_VERSION_PATH.is_file():
        try:
            raw = json.loads(APK_VERSION_PATH.read_text(encoding="utf-8-sig"))
            version = str(raw.get("version") or meta["version"])
            build = int(raw.get("build") or meta["build"])
            meta.update(
                {
                    "version": version,
                    "build": build,
                    "full": str(raw.get("full") or f"{version}+{build}"),
                    "built_at": str(raw.get("built_at") or ""),
                }
            )
        except Exception:
            pass
    if APK_BINARY_PATH.is_file():
        try:
            stat = APK_BINARY_PATH.stat()
            if stat.st_size > 0:
                meta["size_bytes"] = int(stat.st_size)
                meta["apk_available"] = True
        except OSError:
            pass
    return meta
