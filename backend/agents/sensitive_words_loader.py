"""External sensitive-word list loader.

Words come from `data/sensitive_words.txt` (one per line, UTF-8). The file
is optional — when absent or empty, masking is a no-op and user input
passes through unchanged.

Format:
  - one word/phrase per line
  - lines starting with `#` are comments
  - blank lines ignored
  - leading/trailing whitespace stripped

Behavior is MASK & CONTINUE: every match is replaced with `*` of the same
length, then the masked text continues into the pipeline. The pipeline is
never aborted just because a word matched (per user spec 2026-05-15).
"""
from __future__ import annotations

from pathlib import Path

import structlog

log = structlog.get_logger()


_DEFAULT_PATH = Path(__file__).resolve().parents[1] / "data" / "sensitive_words.txt"
_words: set[str] | None = None


def load_words(path: Path | None = None) -> set[str]:
    """Read the words file once and cache in module state. Returns the
    cached set on subsequent calls. Pass an explicit path for tests."""
    global _words
    if _words is not None and path is None:
        return _words

    target = path or _DEFAULT_PATH
    if not target.exists():
        log.info("sensitive_words.file_missing", path=str(target))
        result: set[str] = set()
    else:
        try:
            text = target.read_text(encoding="utf-8")
        except Exception as exc:  # noqa: BLE001
            log.warning("sensitive_words.read_failed",
                        path=str(target), error=str(exc))
            text = ""
        result = set()
        for raw in text.splitlines():
            stripped = raw.strip()
            if not stripped or stripped.startswith("#"):
                continue
            result.add(stripped)
        log.info("sensitive_words.loaded", count=len(result))

    if path is None:
        _words = result
    return result


def mask(text: str, *, replacement_char: str = "*") -> str:
    """Replace every cached word in `text` with same-length `replacement_char`.

    No-op if the word list is empty. Case-sensitive matching by default —
    sensitive word lists tend to be exact (CN words have no case anyway,
    and EN slurs are usually listed in the case they appear in)."""
    words = load_words()
    if not words or not text:
        return text
    masked = text
    for w in words:
        if w in masked:
            masked = masked.replace(w, replacement_char * len(w))
    return masked


def reload() -> int:
    """Force re-read the file. Useful after the user edits the word list
    without restarting the backend. Returns the new word count."""
    global _words
    _words = None
    return len(load_words())
