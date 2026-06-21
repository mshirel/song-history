"""Tests for the Pi deployment compose file (deploy/pi/docker-compose.yml)."""

from pathlib import Path

import pytest
import yaml

COMPOSE_PATH = Path("deploy/pi/docker-compose.yml")


@pytest.mark.skipif(not COMPOSE_PATH.exists(), reason="Pi compose file not present")
class TestImagePinning:
    """All third-party images on the public host must be digest-pinned (#453)."""

    def test_third_party_images_pinned_to_digest(self) -> None:
        services = yaml.safe_load(COMPOSE_PATH.read_text())["services"]
        for name in ("cloudflared", "promtail", "traefik"):
            image = services[name]["image"]
            assert "@sha256:" in image, (
                f"{name} image must be digest-pinned (got {image!r}) — mutable :latest "
                "is non-reproducible and a supply-chain risk on the public host"
            )


@pytest.mark.skipif(not COMPOSE_PATH.exists(), reason="Pi compose file not present")
class TestTrustedProxy:
    """Behind the Cloudflare tunnel the app must trust CF-Connecting-IP so the
    rate limiter (and /metrics IP checks) identify real clients, not the tunnel
    container's IP (#448)."""

    def test_compose_sets_trusted_proxy(self) -> None:
        env = yaml.safe_load(COMPOSE_PATH.read_text())["services"]["song-history"]["environment"]
        assert "TRUSTED_PROXY" in env, (
            "song-history env must set TRUSTED_PROXY so _get_client_ip uses "
            "CF-Connecting-IP instead of bucketing all tunnel traffic as one client"
        )


class TestWatcherHealthcheck:
    """The watcher reuses the app image, which ships a HEALTHCHECK probing
    http://localhost:8000/health (#402). The watcher runs an import loop and does
    NOT serve HTTP, so it must disable the inherited healthcheck — otherwise Docker
    marks the watcher 'unhealthy' and triggers false monitoring alerts."""

    def _services(self) -> dict:
        return yaml.safe_load(COMPOSE_PATH.read_text())["services"]

    def test_watcher_disables_inherited_healthcheck(self) -> None:
        watcher = self._services()["watcher"]
        hc = watcher.get("healthcheck")
        assert hc is not None and hc.get("disable") is True, (
            "watcher must set 'healthcheck: {disable: true}' — it reuses the app "
            "image's HEALTHCHECK (probing :8000) but serves no HTTP, so it would "
            "otherwise be marked unhealthy (#402)."
        )

    def test_song_history_keeps_its_healthcheck(self) -> None:
        """The web service must NOT disable its healthcheck (regression guard)."""
        svc = self._services()["song-history"]
        hc = svc.get("healthcheck") or {}
        assert hc.get("disable") is not True, (
            "song-history must keep a working healthcheck"
        )
