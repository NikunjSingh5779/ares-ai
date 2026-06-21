"""Structured JSON logging configuration.

Provides a ``setup_logging()`` that configures Python's ``logging``
to emit JSON-formatted records with module, level, timestamp, and
message fields suitable for ingestion by Promtail/Loki, Datadog, etc.
"""

from __future__ import annotations

import datetime
import json
import logging
import sys
from typing import Any


class JsonFormatter(logging.Formatter):
    """Format log records as JSON objects, one per line."""

    def format(self, record: logging.LogRecord) -> str:
        dt = datetime.datetime.fromtimestamp(record.created, datetime.timezone.utc)
        payload: dict[str, Any] = {
            "timestamp": dt.isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "level": record.levelname,
            "module": record.module,
            "name": record.name,
            "message": record.getMessage(),
        }

        # Include exception info if present
        if record.exc_info and record.exc_info[0]:
            payload["exception"] = self.formatException(record.exc_info)

        # Include any extra fields set by the caller via ``extra={}``
        for key, value in record.__dict__.items():
            if key not in ("args", "asctime", "created", "exc_info", "exc_text",
                           "filename", "funcName", "id", "levelname", "levelno",
                           "lineno", "module", "msecs", "message", "msg",
                           "name", "pathname", "process", "processName",
                           "relativeCreated", "stack_info", "thread", "threadName"):
                payload[key] = value

        return json.dumps(payload, default=str)


def setup_logging(level: str | int = logging.INFO) -> None:
    """Configure the root logger with JSON formatting.

    Args:
        level: Log level string (e.g. ``"INFO"``, ``"DEBUG"``) or integer.
    """
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())

    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()
    root.addHandler(handler)
