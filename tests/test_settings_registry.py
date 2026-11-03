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
        for key in ("JWT_SECRET", "DATABASE_URL", "ARACHNE_PLUGINS", "TOFU_STATE_ROOT", "SOMETHING_NEW"):
            with self.subTest(key=key), self.assertRaises(ValueError):
                settings.set_override(key, "123", actor="admin")

    def test_restart_scoped_urls_and_boolean_overrides(self):
        settings.set_override("FORGEJO_URL", "https://git.internal:3000/", actor="admin")
        settings.set_override("FORGEJO_VERIFY_TLS", "FALSE", actor="admin")
        settings.set_override("BUS_BACKEND", "nats", actor="admin")
        rows = {item["key"]: item for item in settings.list_settings()}
        self.assertEqual(rows["FORGEJO_URL"]["value"], "https://git.internal:3000")
        self.assertEqual(rows["FORGEJO_VERIFY_TLS"]["value"], "false")
        self.assertTrue(rows["FORGEJO_URL"]["editable"])
        self.assertEqual(rows["BUS_BACKEND"]["input_kind"], "bus")
        settings.reset_override("FORGEJO_URL", actor="admin")
        rows = {item["key"]: item for item in settings.list_settings()}
        self.assertFalse(rows["FORGEJO_URL"]["is_overridden"])

    def test_bad_restart_url_and_invalid_selection_are_rejected(self):
        for key, value in (
            ("FORGEJO_URL", "file:///etc/passwd"),
            ("NEXUS_URL", "https://user:pass@internal"),
            ("ARACHNE_URL", "javascript:alert(1)"),
            ("GITLAB_URL", "https://some host/"),
            ("NATS_URL", "https://nats.internal:4222"),
            ("BUS_BACKEND", "rabbitmq"),
            ("FORGEJO_VERIFY_TLS", "sometimes"),
        ):
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                settings.set_override(key, value, actor="admin")

    def test_startup_overrides_applied_before_imports(self):
        settings.set_override("GITLAB_URL", "https://gitlab.internal", actor="admin")
        with patch.dict(os.environ, {"GITLAB_URL": "https://old.example"}, clear=False):
            settings.apply_startup_overrides()
            self.assertEqual(os.environ["GITLAB_URL"], "https://gitlab.internal")
            self.assertFalse(settings.restart_is_pending())
            settings.set_override("GITLAB_URL", "https://new.internal", actor="admin")
            self.assertTrue(settings.restart_is_pending())
            settings.reset_override("GITLAB_URL", actor="admin")
            self.assertTrue(settings.restart_is_pending())
        settings._APPLIED_RESTART_VALUES.clear()
        settings._RESTART_BASE_ENV.clear()

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
