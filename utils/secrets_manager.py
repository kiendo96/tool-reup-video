"""Local-only API key persistence.

The secrets file is intentionally stored outside git via .gitignore.
Never log or display raw key values.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict

SECRETS_PATH = Path("config") / "local_secrets.json"

DEFAULT_SECRETS = {
    "gemini_api_key": "",
    "deepseek_api_key": "",
    "gemini_tts_api_key": "",
    "last_translator_type": "deepseek",
    "last_model_name": "deepseek-chat",
}


def load_secrets() -> Dict[str, str]:
    if not SECRETS_PATH.exists():
        return DEFAULT_SECRETS.copy()
    try:
        data = json.loads(SECRETS_PATH.read_text(encoding="utf-8"))
        merged = DEFAULT_SECRETS.copy()
        merged.update({k: v for k, v in data.items() if isinstance(v, str)})
        return merged
    except Exception:
        return DEFAULT_SECRETS.copy()


def save_secrets(data: Dict[str, str]) -> None:
    SECRETS_PATH.parent.mkdir(parents=True, exist_ok=True)
    current = load_secrets()
    current.update({k: str(v or "") for k, v in data.items()})
    SECRETS_PATH.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")


def clear_secret(key: str) -> None:
    current = load_secrets()
    if key in current:
        current[key] = ""
    save_secrets(current)


def mask_secret(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return "***"
    return f"{value[:3]}***{value[-4:]}"
