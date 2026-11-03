"""Deletion guards for credentials: bindings, hypervisors and shared secret references."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))

# Like other standalone database tests, run this module in an isolated process.
_tmp = tempfile.TemporaryDirectory()
os.environ["DATABASE_URL"] = "sqlite:///" + _tmp.name + "/secrets-delete.db"

from database import Base, SessionLocal, engine
import secrets_store as secrets
from service_credentials import ServiceCredentialBinding
from infrastructure_connections import InfrastructureConnection

Base.metadata.create_all(engine)


class CredentialDeletionTests(unittest.TestCase):
    def setUp(self):
        with SessionLocal() as db:
            db.query(ServiceCredentialBinding).delete()
            db.query(InfrastructureConnection).delete()
            db.query(secrets.CredentialRow).delete()
            db.query(secrets.SecretProviderRow).delete()
            db.commit()
            provider = secrets.SecretProviderRow(
                slug="local", label="local", kind="database", config_json="{}", enabled=True,
            )
            db.add(provider)
            db.commit()
            self.provider_id = provider.id
        self.backend = Mock()

    def credential(self, slug, ref="credentials/shared"):
        with SessionLocal() as db:
            db.add(secrets.CredentialRow(
                slug=slug, label=slug, kind="basic", username="admin@internal",
                provider_id=self.provider_id, secret_ref=ref, metadata_json="{}",
            ))
            db.commit()

    def test_unused_credential_deletes_record_and_secret(self):
        self.credential("unused")
        with patch.object(secrets, "provider_instance", return_value=self.backend):
            result = secrets.delete_credential("unused")
        self.assertTrue(result["secret_deleted"])
        self.backend.delete.assert_called_once_with("credentials/shared")
        with SessionLocal() as db:
            self.assertIsNone(db.query(secrets.CredentialRow).filter_by(slug="unused").first())

    def test_service_binding_prevents_deletion(self):
        self.credential("forgejo")
        with SessionLocal() as db:
            db.add(ServiceCredentialBinding(service="forgejo", credential_slug="forgejo"))
            db.commit()
        with patch.object(secrets, "provider_instance", return_value=self.backend):
            with self.assertRaisesRegex(ValueError, "services: forgejo"):
                secrets.delete_credential("forgejo")
        self.backend.delete.assert_not_called()

    def test_hypervisor_prevents_deletion(self):
        self.credential("ovirt")
        with SessionLocal() as db:
            db.add(InfrastructureConnection(
                slug="engine", label="engine", backend="ovirt",
                endpoint="https://engine/ovirt-engine/api",
                credential_slug="ovirt", enabled=True, insecure=True,
            ))
            db.commit()
        with patch.object(secrets, "provider_instance", return_value=self.backend):
            with self.assertRaisesRegex(ValueError, "hypervisors: engine"):
                secrets.delete_credential("ovirt")
        self.backend.delete.assert_not_called()

    def test_shared_secret_is_preserved(self):
        self.credential("first")
        self.credential("second")
        with patch.object(secrets, "provider_instance", return_value=self.backend):
            result = secrets.delete_credential("first")
        self.assertFalse(result["secret_deleted"])
        self.backend.delete.assert_not_called()
        with SessionLocal() as db:
            self.assertIsNotNone(db.query(secrets.CredentialRow).filter_by(slug="second").first())

    def test_failed_storage_delete_preserves_record(self):
        self.credential("unused")
        self.backend.delete.side_effect = RuntimeError("storage unavailable")
        with patch.object(secrets, "provider_instance", return_value=self.backend):
            with self.assertRaisesRegex(RuntimeError, "storage unavailable"):
                secrets.delete_credential("unused")
        with SessionLocal() as db:
            self.assertIsNotNone(db.query(secrets.CredentialRow).filter_by(slug="unused").first())


if __name__ == "__main__":
    unittest.main()
