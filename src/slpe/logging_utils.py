"""Logging helpers that prevent credential leakage.

The OpenAlex client sends ``api_key`` and ``mailto`` as URL query parameters. Any
logger that prints full URLs (notably httpx at INFO) would write those into log
files. ``RedactingFilter`` rewrites such values to ``REDACTED`` on every record,
and :func:`configure_logging` installs it and quiets the httpx request logger.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

# Matches api_key=... / mailto=... / api-key=... up to the next & or whitespace.
_SECRET_RE = re.compile(r"(?i)\b(api[_-]?key|mailto)=([^&\s\"']+)")


def redact(text: str) -> str:
    return _SECRET_RE.sub(r"\1=REDACTED", text)


class RedactingFilter(logging.Filter):
    """Redacts secret query parameters from the formatted message and args."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = redact(record.msg)
        if record.args:
            if isinstance(record.args, dict):
                record.args = {k: _redact_arg(v) for k, v in record.args.items()}
            else:
                record.args = tuple(_redact_arg(a) for a in record.args)
        return True


def _redact_arg(arg: object) -> object:
    return redact(arg) if isinstance(arg, str) else arg


def configure_logging(log_file: Path | None = None, *, level: int = logging.INFO) -> None:
    """Configure root logging with redaction and a quieter httpx logger."""
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(log_file, encoding="utf-8"))

    redactor = RedactingFilter()
    for h in handlers:
        h.addFilter(redactor)
        h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))

    root = logging.getLogger()
    root.setLevel(level)
    # Replace existing handlers so re-running in one process doesn't duplicate.
    root.handlers = handlers

    # httpx logs the full request URL (with query string) at INFO — quiet it so
    # secrets never reach a handler; our own client logs what we need.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
