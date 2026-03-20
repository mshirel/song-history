"""Tests for the Pushover notification module."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs

import pytest


class TestSendPushover:
    """Unit tests for the Pushover notification function."""

    def test_success_notification_sends_correct_payload(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Successful import should POST title, message, and priority to Pushover."""
        monkeypatch.setenv("PUSHOVER_USER_KEY", "test-user-key")
        monkeypatch.setenv("PUSHOVER_APP_TOKEN", "test-app-token")
        from worship_catalog.notify import send_pushover

        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value = MagicMock(status=200, read=lambda: b'{"status":1}')
            send_pushover(
                title="Import complete",
                message="Worship_2026-03-18.pptx — 12 songs imported",
            )
            mock_urlopen.assert_called_once()
            req = mock_urlopen.call_args[0][0]
            body = parse_qs(req.data.decode())
            assert body["token"] == ["test-app-token"]
            assert body["user"] == ["test-user-key"]
            assert body["title"] == ["Import complete"]
            assert "12 songs imported" in body["message"][0]

    def test_skipped_when_env_vars_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """No notification and no error when PUSHOVER env vars are unset."""
        monkeypatch.delenv("PUSHOVER_USER_KEY", raising=False)
        monkeypatch.delenv("PUSHOVER_APP_TOKEN", raising=False)
        from worship_catalog.notify import send_pushover

        with patch("urllib.request.urlopen") as mock_urlopen:
            send_pushover(title="Test", message="Test message")
            mock_urlopen.assert_not_called()

    def test_failure_notification_includes_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Failed import notification should include the error summary."""
        monkeypatch.setenv("PUSHOVER_USER_KEY", "u")
        monkeypatch.setenv("PUSHOVER_APP_TOKEN", "t")
        from worship_catalog.notify import send_pushover

        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value = MagicMock(status=200, read=lambda: b'{"status":1}')
            send_pushover(
                title="Import failed",
                message="Worship_2026-03-18.pptx — ValueError: no slides found",
                priority=-1,
            )
            req = mock_urlopen.call_args[0][0]
            body = parse_qs(req.data.decode())
            assert "no slides found" in body["message"][0]
            assert body["priority"] == ["-1"]

    def test_network_error_is_swallowed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Notification failure must not raise — log WARNING and return."""
        monkeypatch.setenv("PUSHOVER_USER_KEY", "u")
        monkeypatch.setenv("PUSHOVER_APP_TOKEN", "t")
        from worship_catalog.notify import send_pushover

        with patch("urllib.request.urlopen", side_effect=OSError("connection refused")):
            # Must not raise
            send_pushover(title="Test", message="Test")

    def test_empty_token_treated_as_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Empty string env vars should be treated the same as unset."""
        monkeypatch.setenv("PUSHOVER_USER_KEY", "")
        monkeypatch.setenv("PUSHOVER_APP_TOKEN", "")
        from worship_catalog.notify import send_pushover

        with patch("urllib.request.urlopen") as mock_urlopen:
            send_pushover(title="Test", message="Test")
            mock_urlopen.assert_not_called()

    def test_default_priority_is_zero(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Default priority should be 0 (normal)."""
        monkeypatch.setenv("PUSHOVER_USER_KEY", "u")
        monkeypatch.setenv("PUSHOVER_APP_TOKEN", "t")
        from worship_catalog.notify import send_pushover

        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value = MagicMock(status=200, read=lambda: b'{"status":1}')
            send_pushover(title="Test", message="Test")
            req = mock_urlopen.call_args[0][0]
            body = parse_qs(req.data.decode())
            assert body["priority"] == ["0"]

    def test_logs_warning_on_failure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Notification failure should log at WARNING level."""
        monkeypatch.setenv("PUSHOVER_USER_KEY", "u")
        monkeypatch.setenv("PUSHOVER_APP_TOKEN", "t")
        from worship_catalog.notify import send_pushover

        with (
            patch("urllib.request.urlopen", side_effect=OSError("timeout")),
            patch("worship_catalog.notify._log") as mock_log,
        ):
            send_pushover(title="Test", message="Test")
            mock_log.warning.assert_called_once()


    def test_skipped_when_only_user_key_set(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Notification must not fire when only PUSHOVER_USER_KEY is set."""
        monkeypatch.setenv("PUSHOVER_USER_KEY", "u")
        monkeypatch.delenv("PUSHOVER_APP_TOKEN", raising=False)
        from worship_catalog.notify import send_pushover

        with patch("urllib.request.urlopen") as mock_urlopen:
            send_pushover(title="Test", message="Test")
            mock_urlopen.assert_not_called()

    def test_skipped_when_only_app_token_set(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Notification must not fire when only PUSHOVER_APP_TOKEN is set."""
        monkeypatch.delenv("PUSHOVER_USER_KEY", raising=False)
        monkeypatch.setenv("PUSHOVER_APP_TOKEN", "t")
        from worship_catalog.notify import send_pushover

        with patch("urllib.request.urlopen") as mock_urlopen:
            send_pushover(title="Test", message="Test")
            mock_urlopen.assert_not_called()

    def test_request_uses_post_method(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Request to Pushover API must use HTTP POST."""
        monkeypatch.setenv("PUSHOVER_USER_KEY", "u")
        monkeypatch.setenv("PUSHOVER_APP_TOKEN", "t")
        from worship_catalog.notify import send_pushover

        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value = MagicMock(status=200)
            send_pushover(title="Test", message="Test")
            req = mock_urlopen.call_args[0][0]
            assert req.get_method() == "POST"

    def test_request_targets_pushover_api_url(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Request must target the correct Pushover API endpoint."""
        monkeypatch.setenv("PUSHOVER_USER_KEY", "u")
        monkeypatch.setenv("PUSHOVER_APP_TOKEN", "t")
        from worship_catalog.notify import send_pushover

        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value = MagicMock(status=200)
            send_pushover(title="Test", message="Test")
            req = mock_urlopen.call_args[0][0]
            assert req.full_url == "https://api.pushover.net/1/messages.json"

    def test_warning_log_includes_title(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Warning log on failure should include the notification title."""
        monkeypatch.setenv("PUSHOVER_USER_KEY", "u")
        monkeypatch.setenv("PUSHOVER_APP_TOKEN", "t")
        from worship_catalog.notify import send_pushover

        with (
            patch("urllib.request.urlopen", side_effect=OSError("boom")),
            patch("worship_catalog.notify._log") as mock_log,
        ):
            send_pushover(title="My Title", message="msg")
            args = mock_log.warning.call_args[0]
            # The title should appear in the log args
            assert "My Title" in args


class TestImportNotificationIntegration:
    """Verify _run_import_in_background calls send_pushover."""

    def test_successful_import_triggers_notification(self, tmp_path: Path) -> None:
        """Background import completing successfully should call send_pushover."""
        from worship_catalog.web.app import _run_import_in_background

        pptx_path = tmp_path / "test.pptx"
        pptx_path.touch()

        mock_result = MagicMock()
        mock_result.service_date = "2026-03-18"
        mock_result.service_name = "AM"
        mock_result.song_leader = None
        mock_result.preacher = None
        mock_result.sermon_title = None
        mock_result.songs = []

        with (
            patch("worship_catalog.web.app._get_db") as mock_get_db,
            patch("worship_catalog.web.app.send_pushover") as mock_notify,
            patch("worship_catalog.extractor.extract_songs", return_value=mock_result),
            patch("worship_catalog.pptx_reader.compute_file_hash", return_value="abc123"),
        ):
            mock_db = MagicMock()
            mock_db.cursor.return_value.fetchone.return_value = None
            mock_get_db.return_value = mock_db

            _run_import_in_background("job-123", pptx_path)

            mock_notify.assert_called_once()
            call_kwargs = mock_notify.call_args
            title = call_kwargs[1].get("title") or call_kwargs[0][0]
            assert "complete" in title.lower() or "success" in title.lower()

    def test_failed_import_triggers_notification(self, tmp_path: Path) -> None:
        """Background import failing should call send_pushover with error details."""
        from worship_catalog.web.app import _run_import_in_background

        pptx_path = tmp_path / "test.pptx"
        pptx_path.touch()

        with (
            patch("worship_catalog.web.app._get_db") as mock_get_db,
            patch("worship_catalog.web.app.send_pushover") as mock_notify,
            patch(
                "worship_catalog.extractor.extract_songs",
                side_effect=ValueError("no slides found"),
            ),
        ):
            mock_db = MagicMock()
            mock_get_db.return_value = mock_db

            _run_import_in_background("job-456", pptx_path)

            mock_notify.assert_called_once()
            call_kwargs = mock_notify.call_args
            title = call_kwargs[1].get("title") or call_kwargs[0][0]
            assert "fail" in title.lower()
            message = call_kwargs[1].get("message") or call_kwargs[0][1]
            assert "no slides found" in message
