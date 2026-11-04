"""Render production templates against connection and ACL edge cases."""
from html.parser import HTMLParser
from pathlib import Path
from types import SimpleNamespace

from jinja2 import Environment, FileSystemLoader, select_autoescape


ROOT = Path(__file__).resolve().parents[1]
ENV = Environment(loader=FileSystemLoader(ROOT / "frontend/templates"),
                  autoescape=select_autoescape(["html"]))
BASE = dict(user=dict(username="tester", roles=["admin"]),
            request=SimpleNamespace(url=SimpleNamespace(path="/admin/scenarios")))


class Fields(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.checked = []
        self.forms = []
        self.names = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in ("input", "select", "textarea") and attrs.get("name"):
            self.names.append(attrs["name"])
        if tag == "input" and "checked" in attrs:
            self.checked.append((attrs.get("name"), attrs.get("value")))
        if tag == "form":
            self.forms.append(attrs.get("action"))


def test_concrete_hypervisors_and_disconnected_profiles_are_not_lost():
    connections = [dict(slug=slug, label=slug, backend="proxmox", endpoint="https://" + slug)
                   for slug in ("pve-a", "pve-b", "pve-empty")]
    profiles = [dict(slug=slug, label=slug, connection=connection, os="linux", live=None,
                     enabled=True, healthy=False, vm_id=101, credentials_ref="ssh")
                for slug, connection in (("first", "pve-a"), ("second", "pve-b"),
                                         ("legacy", None), ("orphan", "removed"))]
    html = ENV.get_template("admin/golden_images.html").render(
        **BASE, connections=connections, profiles=profiles, templates_available=[],
        credentials=[], proxmox_error=None)
    assert html.count('<details class="golden-connection-group"') == 5
    for profile in profiles:
        assert html.count('data-slug="' + profile["slug"] + '"') == 1
        assert '/admin/golden-images/' + profile["slug"] + '/delete' in html
    assert "Без гипервизора" in html
    assert "Недоступное подключение: removed" in html
    assert "Для этого гипервизора пока нет профилей." in html


def editor(**overrides):
    context = dict(scenario=None, acl=[], roles=[dict(slug="admin", name="Administrator")],
                   teams=[dict(id=7, name="Platform")], default_acl_roles=["admin"],
                   default_acl_teams=[7], versions=[], components=[], yaml_text="label: Example")
    context.update(overrides)
    return ENV.get_template("admin/scenario_form.html").render(**BASE, **context)


def test_new_scenario_keeps_defaults_for_all_four_acl_actions():
    fields = Fields(editor())
    assert fields.forms == ["/admin/scenarios/save"]
    for action in ("view", "run", "edit", "manage"):
        assert (action + "_roles", "admin") in fields.checked
        assert (action + "_teams", "7") in fields.checked


def test_existing_scenario_does_not_inherit_new_scenario_acl_defaults():
    html = editor(scenario=dict(slug="example", current_version_id=2),
                  acl=[dict(permission="run", subject_type="team", subject_key="7", match_mode="any")],
                  versions=[dict(id=1, version=1, comment="previous", created_at="today")])
    assert Fields(html).checked == [("run_teams", "7")]
    assert '/admin/scenarios/example/versions/1/restore' in html
    assert 'name="definition" required' in html
    assert 'class="dsl-reference"' in html


def test_editor_keeps_yaml_as_text_even_with_html_input():
    html = editor(yaml_text="label: </textarea><script>alert(1)</script>")
    assert "label: &lt;/textarea&gt;&lt;script&gt;alert(1)&lt;/script&gt;" in html


def test_journal_live_rail_preserves_all_server_filters_and_pagination():
    html = ENV.get_template("run_journal.html").render(
        **BASE, admin=True, total=0, actors=[], scenarios=[], groups=[], entries=[],
        descendants=True, page=2, pages=3, page_size=25,
        page_url=lambda n: "/journal?page=" + str(n))
    assert set(Fields(html).names) == {
        "actor", "scenario", "group", "descendants", "status", "q", "sort",
        "direction", "page_size"}
    assert 'method="get"' in html
    assert 'hx-get="/runs/history"' in html
    assert 'id="workspace"' in html
    assert '/journal?page=1' in html and '/journal?page=3' in html
