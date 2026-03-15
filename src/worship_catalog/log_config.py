"""Structured JSON logging configuration for worship-catalog."""

from __future__ import annotations

import json
import logging
import logging.handlers
import os
import time
from pathlib import Path
from typing import Any

# Query-string sanitization (issue #41 — CWE-532 log information exposure)
_SENSITIVE_PARAMS = frozenset({"q", "token", "key", "secret", "api_key", "password"})
_MAX_QS_LOG_LENGTH = 100


def _sanitize_query_string(qs: str) -> str:
    """Redact sensitive params and truncate long query strings before logging."""
    if not qs:
        return ""
    parts = []
    for part in qs.split("&"):
        name = part.split("=", 1)[0].lower()
        if name in _SENSITIVE_PARAMS:
            parts.append(f"{name}=[redacted]")
        else:
            parts.append(part)
    result = "&".join(parts)
    if len(result) > _MAX_QS_LOG_LENGTH:
        result = result[:_MAX_QS_LOG_LENGTH] + "\u2026"
    return result


class _JsonFormatter(logging.Formatter):
    """Emit each log record as a single-line JSON object."""

    def format(self, record: logging.LogRecord) -> str:
        doc: dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        # Merge any extra kwargs passed as `extra={...}` into the top-level doc
        for key, val in record.__dict__.items():
            if key not in (
                "args", "asctime", "created", "exc_info", "exc_text", "filename",
                "funcName", "id", "levelname", "levelno", "lineno", "module",
                "msecs", "message", "msg", "name", "pathname", "process",
                "processName", "relativeCreated", "stack_info", "thread",
                "threadName", "taskName",
            ):
                doc[key] = val
        if record.exc_info:
            doc["exc"] = self.formatException(record.exc_info)
        return json.dumps(doc, default=str)


def setup(
    level: str | None = None,
    log_file: str | None = None,
) -> None:
    """Configure root logger with JSON output.

    Args:
        level:    Log level string (DEBUG/INFO/WARNING/ERROR).
                  Defaults to LOG_LEVEL env var, then INFO.
        log_file: Path to a rotating log file.
                  Defaults to LOG_FILE env var; omit for stdout-only.
    """
    resolved_level = (level or os.environ.get("LOG_LEVEL", "INFO")).upper()
    resolved_file = log_file or os.environ.get("LOG_FILE")

    formatter = _JsonFormatter()

    root = logging.getLogger()
    root.setLevel(resolved_level)

    # Avoid adding duplicate handlers if called more than once (e.g. in tests)
    if not root.handlers:
        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(formatter)
        root.addHandler(stream_handler)

    if resolved_file:
        log_path = Path(resolved_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            log_path,
            maxBytes=10 * 1024 * 1024,  # 10 MB per file
            backupCount=5,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        # Only add if not already present (path check)
        existing_paths = {
            getattr(h, "baseFilename", None) for h in root.handlers
        }
        if str(log_path.resolve()) not in existing_paths:
            root.addHandler(file_handler)

    # Quiet noisy third-party loggers
    logging.getLogger("uvicorn.access").propagate = False
    logging.getLogger("uvicorn.error").setLevel(logging.WARNING)


# ---------------------------------------------------------------------------
# ASGI request-logging middleware
# ---------------------------------------------------------------------------

class RequestLoggingMiddleware:
    """Log every HTTP request with method, path, status, and duration."""

    def __init__(self, app: Any) -> None:
        self.app = app
        self._log = logging.getLogger("worship_catalog.web.request")

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        start = time.monotonic()
        method = scope.get("method", "?")
        path = scope.get("path", "?")
        qs = _sanitize_query_string(scope.get("query_string", b"").decode())
        full_path = f"{path}?{qs}" if qs else path

        status_code: list[int] = []

        async def send_with_capture(message: Any) -> None:
            if message["type"] == "http.response.start":
                status_code.append(message["status"])
            await send(message)

        try:
            await self.app(scope, receive, send_with_capture)
        except Exception:
            self._log.exception("Unhandled exception", extra={"method": method, "path": full_path})
            raise
        finally:
            duration_ms = round((time.monotonic() - start) * 1000, 1)
            status = status_code[0] if status_code else 0
            log_fn = self._log.warning if status >= 400 else self._log.info
            log_fn(
                f"{method} {full_path} → {status}",
                extra={
                    "method": method, "path": full_path,
                    "status": status, "duration_ms": duration_ms,
                },
            )
