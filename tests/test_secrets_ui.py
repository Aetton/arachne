"""Guard the Secrets template against broken Jinja markup and UI regressions."""
from pathlib import Path
import unittest

from jinja2 import Environment

TEMPLATE = Path(__file__).resolve().parents[1] / "frontend/templates/admin/secrets.html"


class SecretsTemplateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = TEMPLATE.read_text(encoding="utf-8")

    def test_template_parses(self):
        Environment().parse(self.source)

    def test_required_forms_keep_existing_backend_contract(self):
        for route in (
            "/admin/secrets/credentials/save",
            "/admin/secrets/providers/save",
            "/admin/secrets/bindings/save",
            "/api/admin/secrets/service/test",
            "/api/admin/secrets/provider/test",
        ):
            self.assertIn(route, self.source)

    def test_credential_steps_and_fields(self):
        for field in (
            'id="credential-step-1"',
            'id="credential-step-2"',
            'name="kind"',
            'name="slug"',
            'name="label"',
            'name="username"',
            'name="provider"',
            'name="secret_ref"',
            'name="private_key"',
            'name="password"',
            'name="token"',
        ):
            self.assertIn(field, self.source)

    def test_panels_and_modals(self):
        for panel in ("credentials", "services", "storage"):
            self.assertIn('id="secrets-panel-' + panel + '"', self.source)
        self.assertEqual(self.source.count("<dialog "), 2)
        self.assertEqual(self.source.count("</dialog>"), 2)


if __name__ == "__main__":
    unittest.main()
