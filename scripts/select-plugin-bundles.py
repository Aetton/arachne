"""Prune unselected runtime bundles during image build; no package downloads."""

from pathlib import Path
import shutil
from core.optional_plugins import BUNDLES, installed_bundles

selected = installed_bundles()
root = Path(__file__).resolve().parents[1]
for name, module in BUNDLES.items():
    if name not in selected:
        (root / "api" / (module.replace(".", "/") + ".py")).unlink(missing_ok=True)
        if name.startswith("tofu-"):
            shutil.rmtree(
                root / "tofu" / ("stand" if name == "tofu-proxmox" else "ovirt"),
                ignore_errors=True,
            )
(root / "api/plugins/spiders/ansible_ovirt.py").unlink(missing_ok=True)

import json

(root / "installed-bundles.json").write_text(json.dumps(sorted(selected)))
