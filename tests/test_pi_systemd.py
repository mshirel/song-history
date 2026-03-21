from pathlib import Path


class TestSystemdUnitFile:
    def test_systemd_unit_file_exists(self):
        """A sample systemd unit file must be shipped in deploy/pi/."""
        unit = Path("deploy/pi/worship-catalog.service")
        assert unit.exists(), "deploy/pi/worship-catalog.service is missing"

    def test_unit_file_runs_as_songs_user(self):
        """The systemd unit must specify User=songs."""
        content = Path("deploy/pi/worship-catalog.service").read_text()
        assert "User=songs" in content

    def test_unit_file_depends_on_docker(self):
        """The unit must declare After=docker.service dependency."""
        content = Path("deploy/pi/worship-catalog.service").read_text()
        assert "After=docker.service" in content
        assert "Requires=docker.service" in content

    def test_unit_file_uses_compose_up(self):
        """ExecStart must invoke docker compose up."""
        content = Path("deploy/pi/worship-catalog.service").read_text()
        assert "docker compose up" in content

    def test_pi_deploy_docs_reference_systemd(self):
        """Pi deployment docs must explain systemd setup."""
        content = Path("docs/pi-deploy.md").read_text()
        assert "systemctl" in content
        assert "worship-catalog.service" in content
