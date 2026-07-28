"""HEAD support on every GET route, and the ``/health`` render proof (#581).

Two related defects, both of the same shape — the process is perfectly healthy while
monitoring is blind or actively wrong:

* **HEAD 405.** FastAPI's ``APIRoute`` does not add ``HEAD`` to a ``GET`` route the way
  plain Starlette's ``Route`` does, so every route answered ``405 Method Not Allowed``.
  UptimeRobot probes with HEAD by default, so a healthy site read as hard-down.
* **Bare 200 proves nothing.** ``/health`` returned ``{"status": "ok"}`` whenever the
  process was up and the DB answered, which stays true when a bad image ships without
  templates or vendored assets — every page 500s or renders unusable, and the monitor
  reports perfect health. Ported from espn-ff #1093.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from starlette.routing import Route


@pytest.fixture
def app_module(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    """The web app with a real, initialised DB, so ``status`` is never the failing half."""
    db_path = tmp_path / "health.db"
    monkeypatch.setenv("DB_PATH", str(db_path))
    monkeypatch.setenv("TESTING", "1")

    from worship_catalog.db import Database

    db = Database(db_path)
    db.connect()
    db.init_schema()
    db.close()

    import worship_catalog.web.app as module

    module._schema_ready = False
    # The transition logger keeps its last result in a module global; reset it so each
    # test starts from a known edge rather than inheriting the previous test's state.
    monkeypatch.setattr(module, "_LAST_RENDER_PROOF", None)
    # Register the sound paths for restoration even though every test below patches them
    # through monkeypatch. The module is imported once per session, so a single direct
    # assignment leaks a broken deployment into every later test.
    monkeypatch.setattr(module, "_STATIC_DIR", module._STATIC_DIR)
    monkeypatch.setattr(module, "_TEMPLATES_DIR", module._TEMPLATES_DIR)
    return module


@pytest.fixture
def client(app_module: Any) -> TestClient:
    return TestClient(app_module.app)


class TestHeadParity:
    """A GET route must answer HEAD — RFC 9110 requires it, and probes rely on it."""

    def test_head_health_returns_200(self, client: TestClient) -> None:
        assert client.head("/health").status_code == 200

    def test_head_songs_returns_200(self, client: TestClient) -> None:
        assert client.head("/songs").status_code == 200

    def test_head_root_redirects_exactly_like_get(self, app_module: Any) -> None:
        """HEAD / must behave as GET / does — a 307 to /songs, not a 405."""
        with TestClient(app_module.app, follow_redirects=False) as c:
            head, get = c.head("/"), c.get("/")
        assert head.status_code == get.status_code == 307
        assert head.headers["location"] == get.headers["location"] == "/songs"

    def test_head_is_never_405(self, client: TestClient) -> None:
        """The exact symptom UptimeRobot reported: 405 with ``allow: GET``."""
        for path in ("/", "/health", "/songs", "/services", "/reports", "/about"):
            resp = client.head(path)
            assert resp.status_code != 405, (
                f"HEAD {path} returned 405 (allow: {resp.headers.get('allow')!r}) — "
                "a HEAD-based monitor reads this whole site as down"
            )

    def test_every_get_route_also_allows_head(self, app_module: Any) -> None:
        """Regression guard: a new ``@app.get`` must not silently reintroduce the gap.

        This is the test that makes the fix durable. Asserting only on today's handful
        of paths would pass forever while the next route added quietly 405s.
        """
        offenders = [
            f"{route.path} {sorted(route.methods)}"
            for route in app_module.app.routes
            if isinstance(route, Route) and route.methods and "GET" in route.methods
            if "HEAD" not in route.methods
        ]
        assert not offenders, "these GET routes do not accept HEAD:\n  " + "\n  ".join(offenders)


class TestOpenApiStaysValid:
    """Routing HEAD must not corrupt the publicly-served schema.

    FastAPI derives ONE operation id per route and reuses it for every method, so a route
    carrying both GET and HEAD emits two operations sharing an id. ``/openapi.json`` is
    served publicly (200 on the live site), and duplicate ``operationId``s make the document
    invalid and break client generators.
    """

    def test_no_duplicate_operation_ids(self, client: TestClient) -> None:
        from collections import Counter

        spec = client.get("/openapi.json").json()
        ids = Counter(
            op["operationId"]
            for item in spec["paths"].values()
            for op in item.values()
            if "operationId" in op
        )
        dupes = {k: v for k, v in ids.items() if v > 1}
        assert not dupes, f"duplicate operationIds in the served schema: {dupes}"

    def test_head_is_routed_but_not_documented(self, client: TestClient) -> None:
        """HEAD is an affordance of the GET operation, not a separate documented one."""
        spec = client.get("/openapi.json").json()
        documented_heads = [p for p, item in spec["paths"].items() if "head" in item]
        assert not documented_heads, f"HEAD leaked into the schema for: {documented_heads}"
        assert "get" in spec["paths"]["/health"]
        assert client.head("/health").status_code == 200

    def test_schema_generation_is_warning_free(self, app_module: Any) -> None:
        """The duplicate-id collision surfaced as 16 UserWarnings; none should remain."""
        import warnings

        app_module.app.openapi_schema = None  # defeat the cache so generation really runs
        try:
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                app_module.app.openapi()
        finally:
            app_module.app.openapi_schema = None
        assert not [w for w in caught if "Duplicate Operation ID" in str(w.message)]

    def test_head_still_routes_after_schema_generation(self, app_module: Any) -> None:
        """The generator strips HEAD from route.methods; it must put every one back."""
        app_module.app.openapi_schema = None
        try:
            app_module.app.openapi()
            with TestClient(app_module.app) as c:
                assert c.head("/health").status_code == 200
                assert c.head("/songs").status_code == 200
        finally:
            app_module.app.openapi_schema = None


class TestRenderProof:
    """``render`` answers "can this deployment still produce a page?"."""

    def test_health_reports_render_ok_on_a_sound_deployment(self, client: TestClient) -> None:
        assert client.get("/health").json() == {"status": "ok", "render": "ok"}

    def test_keyword_monitor_can_match_the_body(self, client: TestClient) -> None:
        """UptimeRobot matches a substring, so the serialised form matters, not just the dict."""
        assert '"render":"ok"' in client.get("/health").text.replace(" ", "")

    def test_missing_vendored_asset_is_degraded(
        self,
        app_module: Any,
        client: TestClient,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A bad image COPY drops htmx.min.js — every page still returns 200, unusably."""
        empty = tmp_path / "no_static"
        empty.mkdir()
        monkeypatch.setattr(app_module, "_STATIC_DIR", empty)
        assert client.get("/health").json()["render"] == "degraded"

    def test_missing_template_dir_is_degraded(
        self,
        app_module: Any,
        client: TestClient,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(app_module, "_TEMPLATES_DIR", tmp_path / "gone")
        assert client.get("/health").json()["render"] == "degraded"

    def test_unloadable_base_template_is_degraded(
        self, app_module: Any, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A Jinja syntax error in base.html is caught by loading (and so compiling) it."""

        def _boom(_name: str) -> None:
            raise RuntimeError("template is broken")

        monkeypatch.setattr(app_module.templates, "get_template", _boom)
        assert client.get("/health").json()["render"] == "degraded"

    def test_degraded_still_returns_http_200(
        self,
        app_module: Any,
        client: TestClient,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The single most important assertion in this file.

        The container HEALTHCHECK and the compose healthcheck both call ``urlopen``, which
        raises on any non-2xx. If a degraded render dropped the status code, a cosmetic
        asset fault would restart the container in production — trading a monitoring gap
        for a real availability bug. The distinction lives in the body only.
        """
        empty = tmp_path / "no_static2"
        empty.mkdir()
        monkeypatch.setattr(app_module, "_STATIC_DIR", empty)
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["render"] == "degraded"

    def test_render_proof_never_raises(
        self, app_module: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """It sits behind a public unauthenticated path; a raise would become a 500."""

        def _boom(_name: str) -> None:
            raise RuntimeError("nope")

        monkeypatch.setattr(app_module.templates, "get_template", _boom)
        monkeypatch.setattr(app_module, "_STATIC_DIR", None)  # make .is_file() blow up too
        assert app_module._render_proof() == "degraded"

    def test_head_health_runs_the_proof_without_error(self, client: TestClient) -> None:
        """The probe method that started all this must exercise the same path."""
        assert client.head("/health").status_code == 200


class TestRenderProofLogging:
    """``/health`` is hit every 30s/60s/300s — a degraded deployment must not flood Loki."""

    def test_degraded_logs_once_not_once_per_probe(
        self,
        app_module: Any,
        client: TestClient,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        empty = tmp_path / "no_static3"
        empty.mkdir()
        monkeypatch.setattr(app_module, "_STATIC_DIR", empty)
        with caplog.at_level(logging.WARNING, logger="worship_catalog.web"):
            for _ in range(5):
                client.get("/health")
        degraded = [r for r in caplog.records if "DEGRADED" in r.getMessage()]
        assert len(degraded) == 1, (
            f"logged {len(degraded)} times for 5 probes — at 3 probes/minute forever, "
            "the one line worth seeing is buried in copies of itself"
        )

    def test_recovery_is_logged(
        self,
        app_module: Any,
        client: TestClient,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Both edges matter: a silent recovery leaves an operator chasing a fixed fault."""
        empty = tmp_path / "no_static4"
        empty.mkdir()
        sound = app_module._STATIC_DIR
        monkeypatch.setattr(app_module, "_STATIC_DIR", empty)
        with caplog.at_level(logging.WARNING, logger="worship_catalog.web"):
            client.get("/health")
            monkeypatch.setattr(app_module, "_STATIC_DIR", sound)
            client.get("/health")
        assert any("RECOVERED" in r.getMessage() for r in caplog.records)

    def test_a_sound_deployment_logs_nothing_on_startup(
        self, client: TestClient, caplog: pytest.LogCaptureFixture
    ) -> None:
        """No "recovered" line for a deployment that was never broken."""
        with caplog.at_level(logging.WARNING, logger="worship_catalog.web"):
            client.get("/health")
        assert not [r for r in caplog.records if "render proof" in r.getMessage()]
