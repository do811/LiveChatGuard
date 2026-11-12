"""Local, bounded operational logs. Never write OAuth credentials or chat bodies here.

This is separate from the SQLite YouTube-data history. Diagnostic events contain
only status codes, durations, retry counts and exception classes/messages.
"""

from __future__ import annotations

import logging
import re
import threading
from logging.handlers import RotatingFileHandler
from pathlib import Path

from .settings import data_dir

_LOCK = threading.Lock()
_LOGGER = logging.getLogger("livechat_guard")


class _SensitiveDataFilter(logging.Filter):
    # A defense-in-depth measure; callers still must NOT log requests/responses.
    _patterns = (
        (re.compile(r"(?i)Bearer\s+[^\s,'\"]+"), "Bearer [REDACTED]"),
        (re.compile(r"(?i)(access_token|refresh_token|client_secret|id_token)\s*[:=]\s*[^\s,}\"]+"),
         r"\1=[REDACTED]"),
    )

    def filter(self, record: logging.LogRecord) -> bool:
        # Do not modify the caller's dicts. Convert log arguments to a message first.
        message = record.getMessage()
        for pattern, replacement in self._patterns:
            message = pattern.sub(replacement, message)
        record.msg = message
        record.args = ()
        return True


def log_path(base: Path | None = None) -> Path:
    return (base or data_dir()) / "logs" / "livechat_guard.log"


def configure_logging(base: Path | None = None) -> logging.Logger:
    """Idempotently configure rotation (2 MiB x 4 files); file is local-only."""
    with _LOCK:
        if _LOGGER.handlers:
            return _LOGGER
        dest = log_path(base)
        dest.parent.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(dest, maxBytes=2 * 1024 * 1024,
                                      backupCount=3, encoding="utf-8")
        handler.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)s %(threadName)s %(message)s", "%Y-%m-%d %H:%M:%S"))
        handler.addFilter(_SensitiveDataFilter())
        _LOGGER.addHandler(handler)
        _LOGGER.setLevel(logging.INFO)
        _LOGGER.propagate = False
        _LOGGER.info("app_logging_initialized version=0.4.0")
        return _LOGGER


def get_logger() -> logging.Logger:
    return configure_logging()


def safe_error_detail(exc: BaseException, max_chars: int = 350) -> str:
    """Concise error detail without OAuth credentials. Never include chat content."""
    try:
        message = str(exc)
    except Exception:
        message = "<detail unavailable>"
    message = message.replace("\r", " ").replace("\n", " ")
    for pattern, replacement in _SensitiveDataFilter._patterns:
        message = pattern.sub(replacement, message)
    return f"{type(exc).__name__}: {message[:max_chars]}"
