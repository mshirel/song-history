"""Tests for the Pi deployment compose file (deploy/pi/docker-compose.yml)."""

import re
from pathlib import Path

import pytest
import yaml

COMPOSE_PATH = Path("deploy/pi/docker-compose.yml")
TRAEFIK_PATH = Path("deploy/pi/traefik/traefik.yml")

# Services that run the first-party application image (ghcr.io/mshirel/song-history).
APP_SERVICES = ("song-history", "watcher")
# Matches a version-pinned tag such as ":v1.2.0".
_SEMVER_TAG = re.compile(r":v\d+\.\d+\.\d+")


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
class TestAppImagePinning:
    """The first-party app image must be immutably pinned, not mutable ':latest'
    (#512). ``docker compose pull`` on a bare ':latest' silently swaps the running
    application code with no digest record and no deterministic rollback target."""

    def test_app_services_use_the_app_image(self) -> None:
        """Guard the assumption behind the other tests: both services run the app
        image (so the pinning assertion below actually covers the app)."""
        services = yaml.safe_load(COMPOSE_PATH.read_text())["services"]
        for name in APP_SERVICES:
            assert services[name]["image"].startswith("ghcr.io/mshirel/song-history"), (
                f"{name} is expected to run the first-party app image"
            )

    def test_app_image_not_bare_latest(self) -> None:
        for name in APP_SERVICES:
            image = yaml.safe_load(COMPOSE_PATH.read_text())["services"][name]["image"]
            assert image != "ghcr.io/mshirel/song-history:latest", (
                f"{name} must not deploy the mutable ':latest' tag (got {image!r})"
            )

    def test_app_image_is_digest_or_version_pinned(self) -> None:
        """Mirror of the issue's regression test: every reference to the app image
        anywhere in the compose file must carry a digest or an ``:vX.Y.Z`` tag."""
        text = COMPOSE_PATH.read_text()
        refs = re.findall(r"ghcr\.io/mshirel/song-history[:@][^\s\"']+", text)
        assert refs, "expected at least one app-image reference in the compose file"
        for ref in refs:
            assert "@sha256:" in ref or _SEMVER_TAG.search(ref), (
                f"app image must be digest- or version-pinned, got {ref!r}"
            )


@pytest.mark.skipif(not COMPOSE_PATH.exists(), reason="Pi compose file not present")
class TestPromtailNotRoot:
    """promtail must not run as root (#514). It reads all container logs; root is
    unnecessary once the log dir is group-readable / ACL'd, and least-privilege
    matters on this internet-exposed host."""

    def test_promtail_runs_non_root(self) -> None:
        services = yaml.safe_load(COMPOSE_PATH.read_text())["services"]
        promtail = next(v for k, v in services.items() if "promtail" in k)
        user = promtail.get("user")
        assert user not in (None, "root", "0", 0), (
            f"promtail must run as an explicit non-root uid (got {user!r})"
        )
        # The uid portion (before any ':gid') must not be 0/root.
        uid = str(user).split(":", 1)[0]
        assert uid not in ("0", "root"), f"promtail uid must be non-root (got {user!r})"


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


class TestAppMemoryLimit:
    """The public app must fit inside the Pi's explicit memory budget (#503)."""

    def test_song_history_has_512_mb_memory_limit(self) -> None:
        service = yaml.safe_load(COMPOSE_PATH.read_text())["services"]["song-history"]
        assert str(service.get("mem_limit", "")).lower() == "512m", (
            "song-history must have an explicit 512 MB Compose memory limit"
        )


@pytest.mark.skipif(not TRAEFIK_PATH.exists(), reason="Pi traefik config not present")
class TestTraefikDashboard:
    """The Traefik API dashboard must not run in insecure mode (#513).

    `api.insecure: true` exposes the unauthenticated dashboard on :8080, leaking
    full routing config. The traefik container also mounts the docker socket, so
    an accidental port publish turns this info-leak into a socket-adjacent
    exposure on the internet-facing Pi. Defense-in-depth: never ship insecure."""

    def test_traefik_dashboard_not_insecure(self) -> None:
        cfg = yaml.safe_load(TRAEFIK_PATH.read_text())
        assert not cfg.get("api", {}).get("insecure", False), (
            "traefik api.insecure must not be true — it exposes the "
            "unauthenticated dashboard on :8080 (#513)."
        )


class TestWatcherHealthcheck:
    """The watcher reuses the app image, whose inherited HEALTHCHECK probes
    http://localhost:8000/health (#402) — wrong for the watcher, which serves no
    HTTP. Rather than disable liveness entirely (#402), the watcher now defines its
    own lightweight heartbeat-based healthcheck so a wedged import loop is caught by
    monitoring; ``restart: unless-stopped`` only catches a full process exit, not a
    hang (#514)."""

    def _services(self) -> dict:
        return yaml.safe_load(COMPOSE_PATH.read_text())["services"]

    def test_watcher_has_an_active_healthcheck(self) -> None:
        watcher = self._services()["watcher"]
        hc = watcher.get("healthcheck")
        assert hc is not None, "watcher must define a healthcheck (#514)"
        assert hc.get("disable") is not True, (
            "watcher healthcheck must not be disabled — a hung import loop would go "
            "undetected (#514)."
        )
        assert hc.get("test"), (
            "watcher healthcheck must define a 'test' command (#514)."
        )

    def test_watcher_does_not_inherit_http_probe(self) -> None:
        """The watcher serves no HTTP, so its healthcheck must not be the app
        image's :8000 probe — it should test the import-loop heartbeat instead."""
        watcher = self._services()["watcher"]
        test = watcher.get("healthcheck", {}).get("test")
        test_str = " ".join(test) if isinstance(test, list) else str(test)
        assert "8000" not in test_str, (
            "watcher healthcheck must not probe :8000 — it serves no HTTP (#514)."
        )

    def test_song_history_keeps_its_healthcheck(self) -> None:
        """The web service must NOT disable its healthcheck (regression guard)."""
        svc = self._services()["song-history"]
        hc = svc.get("healthcheck") or {}
        assert hc.get("disable") is not True, (
            "song-history must keep a working healthcheck"
        )
