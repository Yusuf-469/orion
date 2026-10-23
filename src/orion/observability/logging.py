"""Structured JSON-lines logging with secret redaction.

Redaction happens in the formatter, so every handler that uses JsonFormatter
writes redacted output regardless of where the record came from. Structured
context goes in `extra={"event": {...}}`.
"""

from __future__ import annotations

import json
import logging
import re
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REDACTED = "[REDACTED]"

_SECRET_KEY = re.compile(
    r"(pass(word|wd)?|secret|token|api[_-]?key|authorization|^auth$|cookie|credential|private[_-]?key)",
    re.IGNORECASE,
)

_SECRET_PATTERNS = [
    # key=value / key: value / "key": "value" for secret-looking key names
    re.compile(
        r"""(?P<k>["']?\b[\w-]*(?:pass(?:word|wd)?|secret|token|api[_-]?key|authorization|cookie|credential)[\w-]*["']?\s*[:=]\s*)(?P<v>"[^"]*"|'[^']*'|[^\s,;&]+)""",
        re.IGNORECASE,
    ),
]
_SECRET_VALUES = [
    re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{8,}", re.IGNORECASE),
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}"),            # OpenAI/Anthropic-style keys
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}"),       # GitHub tokens
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),               # AWS access key id
    re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]+"),  # JWT
]


def _redact_str(s: str) -> str:
    # Known token shapes first, so multi-word values like "Bearer <tok>" go whole.
    for p in _SECRET_VALUES:
        s = p.sub(REDACTED, s)
    for p in _SECRET_PATTERNS:
        s = p.sub(lambda m: m.group("k") + REDACTED, s)
    return s


def redact(obj: Any) -> Any:
    """Return a copy of `obj` with secret-looking keys and values replaced."""
    if isinstance(obj, str):
        return _redact_str(obj)
    if isinstance(obj, dict):
        return {
            k: (REDACTED if isinstance(k, str) and _SECRET_KEY.search(k) else redact(v))
            for k, v in obj.items()
        }
    if isinstance(obj, (list, tuple)):
        return [redact(v) for v in obj]
    return obj


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        event = getattr(record, "event", None)
        if event is not None:
            entry["event"] = event
        if record.exc_info:
            entry["exc"] = "".join(traceback.format_exception(*record.exc_info))
        return json.dumps(redact(entry), default=str, ensure_ascii=False)


def setup_logging(log_dir: Path, level: str = "INFO") -> Path:
    """Attach a JSON-lines file handler to the `orion` logger. Returns the file path."""
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / "orion.jsonl"
    logger = logging.getLogger("orion")
    logger.setLevel(level)
    for h in list(logger.handlers):
        if getattr(h, "_orion", False):
            logger.removeHandler(h)
            h.close()
    handler = logging.FileHandler(path, encoding="utf-8")
    handler.setFormatter(JsonFormatter())
    handler._orion = True  # type: ignore[attr-defined]
    logger.addHandler(handler)
    return path
