"""Admin-only metadata endpoint for the scenario editor.

The endpoint merges the live spider registry with editor-facing contracts. New
spiders appear automatically even before a detailed contract is documented.
"""
from __future__ import annotations

from fastapi import Depends

from auth.deps import require_role
from core.registry import all_spiders, all_triggers
from main import app


# Editor-facing contracts live on the backend so the browser never needs to
# know which plugins are installed. Inputs marked required are validated by the
# plugin itself; the rest are useful completion hints.
SPIDER_CONTRACTS: dict[str, dict] = {
    "forgejo": {
        "description": "Dispatch a Forgejo Actions workflow and collect telemetry/artifacts.",
        "actions": ["build", "run"],
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
        "description": "Run ansible-playbook on the Arachne host.",
        "actions": ["build", "deploy", "run"],
        "inputs": {
            "playbook": {"description": "Playbook path; inferred from component when omitted"},
            "component": {},
            "target": {},
            "os": {},
            "version": {},
        },
    },
    "tofu-proxmox": {
        "description": "Provision a Proxmox VM through OpenTofu.",
        "actions": ["provision"],
        "inputs": {
            "name": {"default": "test-stand"},
            "os": {"default": "redos8", "options": ["redos7", "redos8", "windows"]},
            "vcpus": {"default": 4},
            "ram_mb": {"default": 8192},
            "disk_gb": {"default": 40},
        },
    },
    "ansible-ovirt": {
        "description": "Provision an oVirt VM through the ovirt.ovirt Ansible collection.",
        "actions": ["provision"],
        "inputs": {
            "name": {"default": "test-stand"},
            "os": {"default": "redos8", "options": ["redos7", "redos8", "windows"]},
        },
    },
}


@app.get("/api/admin/scenario-dsl")
def scenario_dsl_metadata(user=Depends(require_role("admin"))):
    spiders = []
    for name, spider in sorted(all_spiders().items()):
        contract = SPIDER_CONTRACTS.get(name, {})
        spiders.append({
            "name": name,
            "kind": spider.KIND,
            "description": contract.get("description", "Installed Arachne spider"),
            "actions": contract.get("actions", ["run"]),
            "inputs": contract.get("inputs", {}),
        })

    return {
        "spiders": spiders,
        "triggers": sorted(all_triggers()),
        "param_types": ["string", "choice", "boolean"],
    }
