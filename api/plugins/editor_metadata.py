"""Admin-only metadata endpoint for the scenario editor.

The endpoint merges the live spider registry with editor-facing contracts. New
spiders appear automatically even before a detailed contract is documented.
"""
from __future__ import annotations

from copy import deepcopy

from fastapi import Depends

from auth.deps import require_role
from core.registry import all_spiders, all_triggers
from golden_images import list_profiles
from main import app


# Editor-facing contracts live on the backend so the browser never needs to
# know which plugins are installed. Inputs marked required are validated by the
# plugin itself; the rest are useful completion hints.
#
# Canonical DSL terminology is Weave / Brood / Command. Legacy backend action
# aliases (build/provision/run/deploy) remain accepted by spiders but are not
# advertised by the editor.
SPIDER_CONTRACTS: dict[str, dict] = {
    "forgejo": {
        "description": "Dispatch a Forgejo Actions workflow and collect telemetry/artifacts.",
        "actions": ["weave"],
        "inputs": {
            "repo": {"required": True, "description": "Forgejo repository name"},
            "workflow": {"required": True, "description": "Workflow file name"},
            "owner": {"default": "FORGEJO_OWNER"},
            "ref": {"default": "main"},
            "branch": {"description": "Alias for ref"},
            "component": {},
            "version": {},
        },
    },
    "ansible-local": {
        "description": "Run ansible-playbook on a target or as a local command.",
        "actions": ["command"],
        "inputs": {
            "playbook": {"description": "Playbook path; inferred from component when omitted"},
            "component": {},
            "target": {"description": "Brood target artifact or explicit host"},
            "os": {},
            "version": {},
        },
    },
    "tofu-proxmox": {
        "description": "Create or destroy an ephemeral stand from a Golden Image profile.",
        "actions": ["brood", "destroy"],
        "inputs": {
            "name": {"default": "test-stand"},
            "os": {
                "default": "redos8",
                "options": ["redos7", "redos8", "windows"],
                "description": "OS family; also acts as the default Golden Image profile key",
            },
            "image": {
                "description": "Optional Golden Image profile; defaults to os",
            },
            "lifetime": {
                "description": "Optional lifetime before automatic cleanup: 30m, 2h, 1d"
            },
            "resources": {
                "description": "Optional resource overrides: cpu, memory_gb, disk_gb"
            },
        },
    },
    "ansible-ovirt": {
        "description": "Create an oVirt VM through the ovirt.ovirt Ansible collection.",
        "actions": ["brood"],
        "inputs": {
            "name": {"default": "test-stand"},
            "os": {"default": "redos8", "options": ["redos7", "redos8", "windows"]},
        },
    },
}


@app.get("/api/admin/scenario-dsl")
def scenario_dsl_metadata(user=Depends(require_role("admin"))):
    profiles = [row for row in list_profiles() if row.get("enabled")]
    spiders = []
    for name, spider in sorted(all_spiders().items()):
        contract = deepcopy(SPIDER_CONTRACTS.get(name, {}))
        if name == "tofu-proxmox" and profiles:
            contract.setdefault("inputs", {}).setdefault("image", {})["options"] = [
                row["slug"] for row in profiles
            ]
        spiders.append({
            "name": name,
            "family": getattr(spider, "FAMILY", "weave"),
            "description": contract.get("description", "Installed Arachne spider"),
            "actions": contract.get("actions", [getattr(spider, "FAMILY", "weave")]),
            "inputs": contract.get("inputs", {}),
        })

    return {
        "spiders": spiders,
        "families": ["weave", "brood", "command"],
        "triggers": sorted(all_triggers()),
        "param_types": ["string", "choice", "boolean"],
    }
