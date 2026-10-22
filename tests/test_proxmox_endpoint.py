"""Regression tests for full API endpoints in saved and legacy connections."""
import os
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))
import proxmox_api


class EndpointTests(unittest.TestCase):
    def test_request_and_console_urls(self):
        for prefix in ("", "/pve"):
            root = "https://pve.example:8006" + prefix
            for suffix in ("", "/", "/api2/json", "/api2/json/"):
                for connection in ("", "saved"):
                    with self.subTest(prefix=prefix, suffix=suffix, connection=connection):
                        settings = {
                            "PROXMOX_VE_ENDPOINT": root + suffix,
                            "PROXMOX_VE_API_TOKEN": "user@pve!test=secret",
                            "PROXMOX_VE_INSECURE": "true",
                        }
                        stub = types.ModuleType("infrastructure_connections")
                        stub.execution_env = lambda slug, backend: settings
                        with patch.dict(sys.modules, infrastructure_connections=stub):
                            with patch.dict(os.environ, settings, clear=True):
                                with proxmox_api._client(connection) as client:
                                    request = client.build_request(
                                        "GET", "/cluster/resources", params={"type": "vm"}
                                    )
                                    self.assertEqual(str(request.url),
                                                     root + "/api2/json/cluster/resources?type=vm")
                                console = proxmox_api.novnc_console_url("node", 100, connection=connection)
                                self.assertTrue(console.startswith(root + "/?console=kvm&"))


if __name__ == "__main__":
    unittest.main()
