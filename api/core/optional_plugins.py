"""Optional execution bundles selected at image build or native installation."""

import os
import json
from pathlib import Path

BUNDLES = {
    "tofu-proxmox": "plugins.spiders.tofu_proxmox",
    "tofu-ovirt": "plugins.spiders.tofu_ovirt",
    "ansible-local": "plugins.spiders.ansible_local",
    "koji": "plugins.spiders.koji",
}


def installed_bundles():
    names = {
        n.strip() for n in os.getenv("ARACHNE_PLUGINS", "").split(",") if n.strip()
    }
    unknown = names - BUNDLES.keys()
    if unknown:
        raise ValueError("Unknown ARACHNE_PLUGINS: " + ", ".join(sorted(unknown)))
    manifest = Path(__file__).resolve().parents[2] / "installed-bundles.json"
    if manifest.exists():
        missing = names - set(json.loads(manifest.read_text()))
        if missing:
            raise ValueError(
                "Bundles not installed in this image; rebuild with: "
                + ", ".join(sorted(missing))
            )
    return names


def module_enabled(module):
    # The historical ansible-ovirt module is a synthetic demo, never a real backend.
    if module == "plugins.spiders.ansible_ovirt":
        return False
    for name, path in BUNDLES.items():
        if module == path:
            return name in installed_bundles()
    return True
