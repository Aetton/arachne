"""Admin settings registry: immutable bootstrap keys, validated overrides, redaction and audit."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_root / "api"))
_temp = tempfile.TemporaryDirectory()
os.environ["DATABASE_URL"] = "sqlite:///" + _temp.name + "/settings.db"
from database import Base, engine, SessionLocal
import settings_registry as settings

Base.metadata.create_all(engine)


class RegistryTests(unittest.TestCase):
    def setUp(self):
        with SessionLocal.begin() as db:
            db.query(settings.SettingChange).delete()
            db.query(settings.SettingOverride).delete()
        settings._VALUE_CACHE.clear()

    def test_live_override_and_reset_with_audit(self):
        with patch.dict(os.environ, {"INPUT_SOURCE_CACHE_TTL": "32"}):
            self.assertEqual(settings.get_numeric("INPUT_SOURCE_CACHE_TTL"), 32)
            settings.set_override("INPUT_SOURCE_CACHE_TTL", "5", actor="admin")
            self.assertEqual(settings.get_numeric("INPUT_SOURCE_CACHE_TTL"), 5)
            entries = [r for r in settings.list_settings() if r["key"] == "INPUT_SOURCE_CACHE_TTL"]
            self.assertEqual(entries[0]["source"], "override")
            settings.reset_override("INPUT_SOURCE_CACHE_TTL", actor="admin")
            self.assertEqual(settings.get_numeric("INPUT_SOURCE_CACHE_TTL"), 32)
        with SessionLocal() as db:
            log = db.query(settings.SettingChange).order_by(settings.SettingChange.id).all()
        self.assertEqual(len(log), 2)
        self.assertEqual(log[0].new_value, "5.0")
        self.assertEqual(log[1].new_value, None)

    def test_reject_non_live_secrets_and_unknown_keys(self):
        for key in ("JWT_SECRET", "DATABASE_URL", "BUS_BACKEND", "ARACHNE_PLUGINS", "SOMETHING_NEW"):
            with self.subTest(key=key), self.assertRaises(ValueError):
                settings.set_override(key, "123", actor="admin")

    def test_numeric_input_validation(self):
        for value in ("nan", "inf", "-3", "999999", "not-a-number"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                settings.set_override("FORGEJO_POLL_INTERVAL", value, actor="admin")

    def test_secret_values_are_never_returned(self):
        with patch.dict(os.environ, {"JWT_SECRET": "supersecret", "DATABASE_URL": "postgres://user:password@localhost/db"}):
            rows = {item["key"]: item for item in settings.list_settings()}
            self.assertIsNone(rows["JWT_SECRET"]["value"])
            self.assertIsNone(rows["DATABASE_URL"]["value"])
            self.assertNotIn("supersecret", str(rows))


if __name__ == "__main__":
    unittest.main()
