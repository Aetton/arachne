"""Custom OS-family tags for Golden Images, without database/network access."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))
_tmp = tempfile.TemporaryDirectory()
os.environ["DATABASE_URL"] = "sqlite:///" + _tmp.name + "/golden-tags.db"

from database import Base, SessionLocal, engine
import golden_images

Base.metadata.create_all(engine)


class GoldenTagTests(unittest.TestCase):
    def test_existing_and_custom_tags(self):
        for tag in ("redos8", "redos7", "windows", "astra", "ubuntu-24.04", "Windows-Server-2022"):
            with self.subTest(tag=tag):
                _, _, normalized, vm_id = golden_images.validate_profile(
                    slug="test", label="Test", os_name=tag, vm_id=123
                )
                self.assertEqual(normalized, tag.lower())
                self.assertEqual(vm_id, 123)

    def test_invalid_and_oversized_tags(self):
        for tag in ("", "../bad", "not a tag", "тест", "x" * 33):
            with self.subTest(tag=tag), self.assertRaises(ValueError):
                golden_images.validate_profile(
                    slug="test", label="Test", os_name=tag, vm_id=123
                )

    def test_saved_tag_is_suggested(self):
        with SessionLocal() as db:
            db.add(golden_images.GoldenImageProfile(
                slug="new-image", label="New Image", os="astra",
                backend="proxmox", vm_id=321,
            ))
            db.commit()
        tags = golden_images.list_os_tags()
        self.assertIn("astra", tags)
        self.assertIn("redos8", tags)
        self.assertIn("windows", tags)

    def test_transport_family(self):
        self.assertTrue(golden_images.is_windows_os("windows-server-2022"))
        self.assertFalse(golden_images.is_windows_os("astra"))


if __name__ == "__main__":
    unittest.main()
