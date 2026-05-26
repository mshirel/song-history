"""Guards that the Pi deploy runbook reflects the public-exposure reality (#454)."""

from pathlib import Path

import pytest

DOC = Path("docs/pi-deploy.md")


@pytest.mark.skipif(not DOC.exists(), reason="pi-deploy.md not present")
class TestPiDeployDocAccuracy:
    def _text(self) -> str:
        return DOC.read_text().lower()

    def test_does_not_claim_lan_only(self) -> None:
        doc = self._text()
        assert "lan-only — no public internet exposure" not in doc, (
            "Runbook must not claim LAN-only — the cloudflared tunnel exposes it publicly"
        )

    def test_documents_public_tunnel(self) -> None:
        doc = self._text()
        assert "cloudflare" in doc and "tunnel" in doc
        assert "public" in doc

    def test_documents_host_hardening(self) -> None:
        doc = self._text()
        assert "ufw" in doc or "firewall" in doc          # host firewall step
        assert "chmod 600" in doc and ".env" in doc        # secret perms step
        assert "passwordauthentication no" in doc or "key-only" in doc  # SSH hardening
