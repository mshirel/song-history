"""Tests for pi-songs host-hardening artifacts (#446, #447, #452).

These assert the repo carries reproducible, correct deployment-hardening config
for the public-facing host. They guard against drift/regression in the firewall
and SSH posture that was applied live during Review-11 remediation.
"""

from pathlib import Path

_PI = Path(__file__).parent.parent / "deploy" / "pi"
_PROM = "10.20.100.245"  # the only host allowed to scrape pi-songs


class TestDockerUserFirewall:
    """Docker-published :8000/:2000 must be restricted to the Prometheus scraper,
    since Docker bypasses ufw's INPUT chain (#447)."""

    def _script(self) -> str:
        return (_PI / "firewall" / "docker-user-firewall.sh").read_text()

    def test_script_and_unit_exist(self) -> None:
        assert (_PI / "firewall" / "docker-user-firewall.sh").is_file()
        assert (_PI / "firewall" / "docker-user-firewall.service").is_file()

    def test_restricts_metrics_ports_to_prometheus(self) -> None:
        s = self._script()
        assert _PROM in s, "must allow only the Prometheus scraper"
        for port in ("8000", "2000"):
            assert port in s, f"must cover Docker-published port {port}"
        assert "DROP" in s and "RETURN" in s, "must DROP non-Prometheus, RETURN Prometheus"
        assert "DOCKER-USER" in s, "must use the DOCKER-USER hook (ufw can't filter Docker)"

    def test_unit_runs_after_docker(self) -> None:
        unit = (_PI / "firewall" / "docker-user-firewall.service").read_text()
        assert "After=docker.service" in unit and "WantedBy=multi-user.target" in unit


class TestUfwBaseline:
    """ufw baseline must deny-by-default and allow only SSH(mgmt)/80/443/scraper (#447)."""

    def test_ufw_setup_exists_and_denies_by_default(self) -> None:
        s = (_PI / "firewall" / "ufw-setup.sh").read_text()
        assert "default deny incoming" in s
        assert "10.20.0.0/16" in s and 'from "$MGMT" to any port 22' in s  # SSH mgmt
        assert "443/tcp" in s and "80/tcp" in s                            # Traefik
        assert _PROM in s and 'from "$PROM" to any port 9100' in s         # scrape only

    def test_ufw_does_not_loopback_bind_app_port(self) -> None:
        # Binding :8000 to loopback would break the external Prometheus scrape;
        # the firewall (not a loopback bind) is the chosen control. Guard the intent.
        compose = (_PI / "docker-compose.yml").read_text()
        assert '"127.0.0.1:8000' not in compose, (
            "Do NOT loopback-bind :8000 — it breaks the Prometheus scrape from "
            f"{_PROM}; restrict via ufw + DOCKER-USER instead"
        )


class TestSshHardening:
    """Key-only SSH drop-in must sort before cloud-init and disable passwords (#452)."""

    def test_drop_in_disables_password_auth(self) -> None:
        conf = (_PI / "ssh" / "00-hardening.conf").read_text()
        assert "PasswordAuthentication no" in conf

    def test_drop_in_sorts_before_cloud_init(self) -> None:
        # Must be 00- (or otherwise < 50-cloud-init) so OpenSSH first-match wins.
        assert (_PI / "ssh" / "00-hardening.conf").is_file(), (
            "drop-in must be named 00-* to beat 50-cloud-init.conf (first-match-wins)"
        )
