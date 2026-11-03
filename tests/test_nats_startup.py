"""NATS startup must fail promptly with usable diagnostics."""
import asyncio
import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))

from core.bus.nats_bus import NatsBus


class NatsStartupTests(unittest.TestCase):
    def test_unavailable_server_reports_correct_compose_host(self):
        async def connect(*args, **kwargs):
            raise ConnectionRefusedError(111, "Connection refused")

        stub = SimpleNamespace(connect=connect)
        with patch.dict(sys.modules, {"nats": stub}), patch.dict(os.environ, {"NATS_URL": "nats://nats:4222"}):
            with self.assertRaisesRegex(RuntimeError, "docker compose up -d nats"):
                asyncio.run(NatsBus().start())

    def test_connect_uses_configured_address_and_keeps_reconnects(self):
        mock_connect = AsyncMock(return_value=object())
        stub = SimpleNamespace(connect=mock_connect)
        with patch.dict(sys.modules, {"nats": stub}), patch.dict(os.environ, {"NATS_URL": "nats://nats:4222"}):
            asyncio.run(NatsBus().start())
        mock_connect.assert_awaited_once_with(
            "nats://nats:4222", connect_timeout=2, reconnect_time_wait=1
        )


if __name__ == "__main__":
    unittest.main()
