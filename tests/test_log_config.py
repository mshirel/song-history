"""Tests for worship_catalog.log_config — structured JSON logging."""

import asyncio
import json
import logging
import logging.handlers
from pathlib import Path

import pytest

from worship_catalog.log_config import (
    RequestLoggingMiddleware,
    _JsonFormatter,
    _sanitize_query_string,
    setup,
)


class TestJsonFormatter:
    """Tests for _JsonFormatter.format()."""

    @pytest.fixture(autouse=True)
    def formatter(self):
        self.fmt = _JsonFormatter()

    def _make_record(self, msg="test message", level=logging.INFO, **extra):
        record = logging.LogRecord(
            name="test.logger",
            level=level,
            pathname="",
            lineno=0,
            msg=msg,
            args=(),
            exc_info=None,
        )
        for k, v in extra.items():
            setattr(record, k, v)
        return record

    def test_output_is_valid_json(self):
        record = self._make_record()
        output = self.fmt.format(record)
        parsed = json.loads(output)
        assert isinstance(parsed, dict)

    def test_required_keys_present(self):
        record = self._make_record()
        parsed = json.loads(self.fmt.format(record))
        assert "ts" in parsed
        assert "level" in parsed
        assert "logger" in parsed
        assert "msg" in parsed

    def test_level_value_is_string(self):
        record = self._make_record(level=logging.WARNING)
        parsed = json.loads(self.fmt.format(record))
        assert parsed["level"] == "WARNING"

    def test_extra_kwargs_merged_into_doc(self):
        record = self._make_record(service_date="2026-02-15", rows=12)
        parsed = json.loads(self.fmt.format(record))
        assert parsed["service_date"] == "2026-02-15"
        assert parsed["rows"] == 12

    def test_exc_info_serialized_to_exc_key(self):
        try:
            raise ValueError("boom")
        except ValueError:
            import sys
            exc_info = sys.exc_info()

        record = self._make_record()
        record.exc_info = exc_info
        parsed = json.loads(self.fmt.format(record))
        assert "exc" in parsed
        assert "ValueError" in parsed["exc"]


class TestSetup:
    """Tests for setup() logging configuration."""

    def teardown_method(self):
        """Remove all handlers from root logger after each test."""
        root = logging.getLogger()
        for handler in root.handlers[:]:
            root.removeHandler(handler)
            handler.close()
        root.setLevel(logging.WARNING)  # reset

    def test_default_level_is_info(self, monkeypatch):
        monkeypatch.delenv("LOG_LEVEL", raising=False)
        setup()
        assert logging.getLogger().level == logging.INFO

    def test_log_level_env_var_respected(self, monkeypatch):
        monkeypatch.setenv("LOG_LEVEL", "DEBUG")
        setup()
        assert logging.getLogger().level == logging.DEBUG

    def test_explicit_level_arg(self):
        setup(level="WARNING")
        assert logging.getLogger().level == logging.WARNING

    def test_stream_handler_added(self):
        setup()
        root = logging.getLogger()
        stream_handlers = [h for h in root.handlers if isinstance(h, logging.StreamHandler)
                           and not isinstance(h, logging.handlers.RotatingFileHandler)]
        assert len(stream_handlers) >= 1

    def test_calling_twice_does_not_duplicate_handlers(self):
        setup()
        handler_count_1 = len(logging.getLogger().handlers)
        setup()
        handler_count_2 = len(logging.getLogger().handlers)
        assert handler_count_1 == handler_count_2

    def test_log_file_creates_rotating_handler(self, tmp_path):
        log_file = str(tmp_path / "test.log")
        setup(log_file=log_file)
        root = logging.getLogger()
        file_handlers = [
            h for h in root.handlers
            if isinstance(h, logging.handlers.RotatingFileHandler)
        ]
        assert len(file_handlers) == 1
        assert file_handlers[0].baseFilename == str(Path(log_file).resolve())


_REQUEST_LOGGER = "worship_catalog.web.request"


def _http_scope(query_string: bytes = b"") -> dict:
    return {"type": "http", "method": "GET", "path": "/songs", "query_string": query_string}


def _app_returning(status: int):
    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": status, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    return app


def _run(middleware, scope, sent: list) -> None:
    """Drive the middleware with a real async send (#655).

    asyncio.run() owns its loop; fetching the implicit one raises on 3.14
    when none is running.  No try/except: a failure here must fail the test,
    not leave caplog empty for an assertion loop to skip.
    """

    async def send(message):
        sent.append(message)

    asyncio.run(middleware(scope, None, send))


def _request_records(caplog) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.name == _REQUEST_LOGGER]


class TestRequestLoggingMiddleware:
    """Tests for ASGI request logging middleware."""

    def test_passes_through_non_http_scopes(self, caplog):
        """Non-HTTP scopes (e.g. lifespan) are passed through unchanged and not logged."""
        received = []

        async def app(scope, receive, send):
            received.append(scope["type"])

        with caplog.at_level(logging.INFO, logger=_REQUEST_LOGGER):
            asyncio.run(RequestLoggingMiddleware(app)({"type": "lifespan"}, None, None))
        assert received == ["lifespan"]
        assert _request_records(caplog) == [], "non-HTTP scopes must not be logged"

    def test_http_request_logged(self, caplog):
        """HTTP requests produce one INFO record with method, path, status, duration."""
        sent: list = []
        with caplog.at_level(logging.INFO, logger=_REQUEST_LOGGER):
            _run(RequestLoggingMiddleware(_app_returning(200)), _http_scope(), sent)

        records = _request_records(caplog)
        assert len(records) == 1
        record = records[0]
        assert record.levelname == "INFO"
        assert (record.method, record.path, record.status) == ("GET", "/songs", 200)
        assert isinstance(record.duration_ms, float)
        assert [m["type"] for m in sent] == ["http.response.start", "http.response.body"]

    def test_4xx_logged_as_warning(self, caplog):
        """Client-error responses are logged at WARNING, not INFO."""
        with caplog.at_level(logging.INFO, logger=_REQUEST_LOGGER):
            _run(RequestLoggingMiddleware(_app_returning(404)), _http_scope(), [])

        (record,) = _request_records(caplog)
        assert record.levelname == "WARNING"
        assert record.status == 404

    def test_unhandled_exception_logged_and_reraised(self, caplog):
        """An app exception is logged at ERROR, re-raised, and still gets a status-0 record."""

        async def app(scope, receive, send):
            raise ValueError("boom")

        with caplog.at_level(logging.INFO, logger=_REQUEST_LOGGER), pytest.raises(ValueError):
            _run(RequestLoggingMiddleware(app), _http_scope(), [])

        records = _request_records(caplog)
        assert [r.levelname for r in records] == ["ERROR", "INFO"]
        assert records[-1].status == 0


class TestSanitizeQueryString:
    """Tests for _sanitize_query_string() — issue #41."""

    def test_empty_string_returns_empty(self) -> None:
        assert _sanitize_query_string("") == ""

    def test_clean_param_is_returned_unchanged(self) -> None:
        result = _sanitize_query_string("sort=title&order=asc")
        assert result == "sort=title&order=asc"

    def test_q_param_value_is_redacted(self) -> None:
        result = _sanitize_query_string("q=John+Smith")
        assert "John" not in result
        assert "Smith" not in result
        assert "q=" in result
        assert "[redacted]" in result

    def test_token_param_is_redacted(self) -> None:
        result = _sanitize_query_string("token=abc123")
        assert "abc123" not in result
        assert "[redacted]" in result

    def test_multiple_sensitive_params_all_redacted(self) -> None:
        result = _sanitize_query_string("token=secret&q=name&sort=title")
        assert "secret" not in result
        assert "name" not in result
        assert "sort=title" in result

    def test_long_query_string_is_truncated(self) -> None:
        long_qs = "x=" + "A" * 200
        result = _sanitize_query_string(long_qs)
        assert len(result) <= 110  # 100 chars + "…" ellipsis

    def test_path_without_query_string_unaffected(self) -> None:
        """_sanitize_query_string with no input returns empty."""
        assert _sanitize_query_string("") == ""

    def test_middleware_redacts_q_in_logged_path(self, caplog) -> None:
        """Query string with ?q= is sanitized before appearing in log records."""
        with caplog.at_level(logging.INFO, logger=_REQUEST_LOGGER):
            _run(
                RequestLoggingMiddleware(_app_returning(200)),
                _http_scope(b"q=PastorJohnSmith"),
                [],
            )

        records = _request_records(caplog)
        assert records, "middleware must emit a record, or the redaction check is vacuous"
        assert records[0].levelname == "INFO", "redaction must be checked on the normal path"
        assert records[0].path == "/songs?q=[redacted]"
        for record in records:
            assert "PastorJohnSmith" not in record.path, (
                "Search query value must not appear verbatim in log records"
            )
            assert "PastorJohnSmith" not in record.getMessage()
