from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import structlog

from bootstrap.paths import APP_CONFIG_PATH, LAST_STATE_PATH

log = structlog.get_logger()

_DEFAULT_CONFIG: dict[str, Any] = {
    "theme": "system",
    "language": "zh-CN",
    "last_page": "/",
    "window": {"width": 1280, "height": 800},
}


def load_app_config() -> dict[str, Any]:
    if not APP_CONFIG_PATH.exists():
        save_app_config(_DEFAULT_CONFIG)
        return dict(_DEFAULT_CONFIG)

    try:
        import yaml
        with open(APP_CONFIG_PATH, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        log.info("config.loaded", path=str(APP_CONFIG_PATH))
        return data
    except ImportError:
        try:
            with open(APP_CONFIG_PATH, encoding="utf-8") as f:
                data = json.load(f)
            return data
        except Exception:
            log.warning("config.load_failed_json_fallback", path=str(APP_CONFIG_PATH))
            return dict(_DEFAULT_CONFIG)
    except Exception as e:
        log.warning("config.load_failed", error=str(e))
        return dict(_DEFAULT_CONFIG)


def save_app_config(config: dict[str, Any]) -> None:
    APP_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        import yaml
        with open(APP_CONFIG_PATH, "w", encoding="utf-8") as f:
            yaml.dump(config, f, allow_unicode=True, default_flow_style=False)
    except ImportError:
        with open(APP_CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)


def load_last_state() -> dict[str, Any] | None:
    if not LAST_STATE_PATH.exists():
        return None

    try:
        with open(LAST_STATE_PATH, encoding="utf-8") as f:
            data = json.load(f)
        log.info("last_state.loaded", path=str(LAST_STATE_PATH))
        return data
    except Exception as e:
        broken_path = LAST_STATE_PATH.with_suffix(f".broken.{int(__import__('time').time())}.json")
        try:
            LAST_STATE_PATH.rename(broken_path)
        except Exception:
            pass
        log.warning("last_state.corrupted", error=str(e), renamed_to=str(broken_path))
        return None


def save_last_state(state: dict[str, Any]) -> None:
    LAST_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(LAST_STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def clear_last_state() -> None:
    if LAST_STATE_PATH.exists():
        LAST_STATE_PATH.unlink()
