"""Runtime configuration: data directories, API keys, defaults."""
from __future__ import annotations

import json
import os
from typing import Any, Dict

PKG_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_DIR = os.path.dirname(PKG_DIR)


def data_dir() -> str:
    d = os.environ.get("RLPCB_HOME") or os.path.join(os.path.expanduser("~"), ".rlpcb")
    os.makedirs(d, exist_ok=True)
    return d


def knowledge_dir() -> str:
    return os.environ.get("RLPCB_KNOWLEDGE") or os.path.join(REPO_DIR, "knowledge")


def settings_path() -> str:
    return os.path.join(data_dir(), "settings.json")


DEFAULTS: Dict[str, Any] = {
    "model": "auto",
    "provider": "anthropic",  # anthropic | openai-compatible
    "openai_base_url": "http://localhost:11434/v1",
    "max_tokens": 8000,
    "active_project": None,
    "server_port": 8765,
    "allow_file_writes": True,
    "backup_before_write": True,
    "freerouting_jar": None,
}


def load_settings() -> Dict[str, Any]:
    s = dict(DEFAULTS)
    try:
        with open(settings_path(), encoding="utf-8-sig") as f:
            s.update(json.load(f))
    except (OSError, ValueError):
        pass
    return s


def save_settings(updates: Dict[str, Any]) -> Dict[str, Any]:
    s = load_settings()
    s.update(updates)
    with open(settings_path(), "w", encoding="utf-8") as f:
        json.dump(s, f, indent=2)
    return s
