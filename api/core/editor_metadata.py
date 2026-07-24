"""Editor-facing metadata for installed Arachne plugins.

The contracts are shared by the server-rendered DSL reference and the optional
JSON endpoint used by editor completion. Keeping them outside an HTTP plugin
avoids making the UI depend on plugin import timing.
"""
from __future__ import annotations

from core.registry import all_spiders, all_triggers


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
    "scenario": {
        "description": "Run another Arachne scenario as a child step.",
        "actions": ["run"],
        "inputs": {
            "scenario": {"required": True, "description": "Child scenario slug"},
            "params": {"description": "Parameters passed to the child scenario"},
        },
    },
}


def scenario_dsl_metadata() -> dict:
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
