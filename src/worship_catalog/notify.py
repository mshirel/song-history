"""Pushover push-notification helper.

Sends mobile/desktop alerts via the Pushover API.  Notifications are
fire-and-forget: failures are logged at WARNING and never propagated.

Required env vars (both must be set and non-empty for notifications to fire):
  PUSHOVER_USER_KEY   – your Pushover user/group key
  PUSHOVER_APP_TOKEN  – your Pushover application API token
"""

from __future__ import annotations

import logging
import os
import urllib.parse
import urllib.request

_log = logging.getLogger("worship_catalog.notify")

_PUSHOVER_API_URL = "https://api.pushover.net/1/messages.json"


def send_pushover(
    *,
    title: str,
    message: str,
    priority: int = 0,
) -> None:
    """Send a push notification via Pushover.

    Silently returns (no error) when credentials are missing or when the
    HTTP request fails.
    """
    user_key = os.environ.get("PUSHOVER_USER_KEY", "")
    app_token = os.environ.get("PUSHOVER_APP_TOKEN", "")

    if not user_key or not app_token:
        _log.debug("Pushover notification skipped — credentials not configured")
        return

    payload = urllib.parse.urlencode(
        {
            "token": app_token,
            "user": user_key,
            "title": title,
            "message": message,
            "priority": str(priority),
        }
    ).encode()

    req = urllib.request.Request(_PUSHOVER_API_URL, data=payload, method="POST")

    try:
        urllib.request.urlopen(req)  # noqa: S310  # nosec B310
    except Exception:  # noqa: BLE001
        _log.warning("Pushover notification failed for %r", title, exc_info=True)
