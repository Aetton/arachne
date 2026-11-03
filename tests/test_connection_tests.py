"""Unit tests for read-only connection probes (no live services)."""
import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))

import connection_tests as probes


class TestConnectionProbes(unittest.TestCase):
    def test_url_rejects_embedded_secrets_and_query(self):
        for value in ("http://host", "https://user:pass@host", "https://host/?token=secret", "https://host/#frag"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                probes._endpoint(value)

    @patch.object(probes, "resolve_credential")
    @patch.object(probes, "_probe")
    def test_unsaved_proxmox_uses_selected_values(self, probe, resolve):
        resolve.return_value = SimpleNamespace(
            kind="token", username="", values={"token": "secret-token"}
        )
        probe.return_value = {"ok": True, "stage": "api"}
        result = probes.hypervisor("proxmox", "https://pve:8006/api2/json",
                                   "new-credential", True)
        self.assertTrue(result["ok"])
        args, kwargs = probe.call_args
        self.assertEqual(args[0], "https://pve:8006/api2/json/cluster/resources?type=vm")
        self.assertEqual(kwargs["headers"]["Authorization"], "PVEAPIToken=secret-token")
        self.assertFalse(kwargs["verify"])
        resolve.assert_called_once_with("new-credential")

    @patch.object(probes, "resolve_credential")
    @patch.object(probes, "_probe")
    def test_ovirt_template_check(self, probe, resolve):
        resolve.return_value = SimpleNamespace(
            kind="basic", username="admin@internal", values={"password": "private"}
        )
        probe.return_value = {"ok": True}
        probes.hypervisor("ovirt", "https://engine/ovirt-engine/api", "cred", False)
        args, kwargs = probe.call_args
        self.assertEqual(args[0], "https://engine/ovirt-engine/api/templates")
        self.assertEqual(kwargs["auth"], ("admin@internal", "private"))
        self.assertTrue(kwargs["verify"])

    @patch.object(probes, "_probe")
    @patch.object(probes, "resolve_credential")
    def test_service_uses_selected_token(self, resolve, probe):
        resolve.return_value = SimpleNamespace(kind="token", username="", values={"token": "secret"})
        with patch.dict(os.environ, {"FORGEJO_URL": "https://git.example"}):
            probes.service("forgejo", "forgejo-cred")
        self.assertEqual(probe.call_args.args[0], "https://git.example/api/v1/user")
        self.assertEqual(probe.call_args.kwargs["headers"]["Authorization"], "token secret")

    @patch.object(probes, "_probe")
    @patch.object(probes, "VaultSecretProvider")
    def test_vault_checks_token_auth_not_public_health(self, vault, probe):
        vault.return_value._headers.return_value = {"X-Vault-Token": "secret"}
        probes.provider("vault", {"address": "https://vault.example"})
        self.assertEqual(probe.call_args.args[0], "https://vault.example/v1/auth/token/lookup-self")
        self.assertEqual(probe.call_args.kwargs["headers"]["X-Vault-Token"], "secret")


if __name__ == "__main__":
    unittest.main()
