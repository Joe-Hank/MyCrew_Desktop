from pathlib import Path
import os

_DEV_MODE = os.getenv("MYCREW_DEV", "0") == "1"

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

DATA_DIR = PROJECT_ROOT / "data"
CONFIG_DIR = DATA_DIR / "config"
DB_DIR = DATA_DIR / "db"
LOG_DIR = DATA_DIR / "logs"
CACHE_DIR = DATA_DIR / "cache"
SECRETS_DIR = DATA_DIR / "secrets"
RUNTIME_DIR = DATA_DIR / "runtime"
OUTPUT_DIR = PROJECT_ROOT / "output"

DB_PATH = DB_DIR / "mycrew.db"
DB_URL = f"sqlite+aiosqlite:///{DB_PATH}"
APP_CONFIG_PATH = CONFIG_DIR / "app.yaml"
LAST_STATE_PATH = RUNTIME_DIR / "last_state.json"

SRC_TOOLS_DIR = PROJECT_ROOT / "src" / "tools"

DEFAULT_PORT = int(os.getenv("MYCREW_BACKEND_PORT", "18321"))
PORT_RANGE = range(18321, 18400)


def ensure_dirs() -> None:
    for d in (CONFIG_DIR, DB_DIR, LOG_DIR, CACHE_DIR, SECRETS_DIR, RUNTIME_DIR, OUTPUT_DIR):
        d.mkdir(parents=True, exist_ok=True)
