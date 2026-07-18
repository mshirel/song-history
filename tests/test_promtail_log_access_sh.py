"""Tests for the non-root Promtail Docker-log access helper."""

import stat
import subprocess
from pathlib import Path

SCRIPT = Path("deploy/pi/scripts/prepare-promtail-log-access.sh")
PATH_UNIT = Path("deploy/pi/systemd/promtail-log-access.path")
SERVICE_UNIT = Path("deploy/pi/systemd/promtail-log-access.service")


def test_grants_group_enumeration_without_changing_log_mode(tmp_path: Path) -> None:
    containers = tmp_path / "containers"
    container = containers / ("a" * 64)
    container.mkdir(parents=True)
    log = container / f"{'a' * 64}-json.log"
    log.write_text("one line\n")
    containers.chmod(0o710)
    container.chmod(0o710)
    log.chmod(0o640)

    subprocess.run([str(SCRIPT), str(containers)], check=True)

    assert stat.S_IMODE(containers.stat().st_mode) == 0o750
    assert stat.S_IMODE(container.stat().st_mode) == 0o750
    assert stat.S_IMODE(log.stat().st_mode) == 0o640


def test_rejects_missing_container_directory(tmp_path: Path) -> None:
    result = subprocess.run([str(SCRIPT), str(tmp_path / "missing")], check=False)

    assert result.returncode != 0


def test_systemd_path_reapplies_access_for_new_containers() -> None:
    path_unit = PATH_UNIT.read_text()
    service_unit = SERVICE_UNIT.read_text()

    assert "PathChanged=/var/lib/docker/containers" in path_unit
    assert "promtail-log-access.service" in path_unit
    assert "/opt/song-history/scripts/prepare-promtail-log-access.sh" in service_unit
