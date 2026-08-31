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


DOCS_BASE = "/wiki/ru"

# Editor-facing contracts live on the backend so the browser never needs to
# know which plugins are installed. This is also the single source of truth for
# hover help, examples and completion documentation in the scenario editor.
SPIDER_CONTRACTS: dict[str, dict] = {
    "forgejo": {
        "description": "Запускает Forgejo Actions workflow и возвращает логи и артефакты сборки.",
        "docs_url": f"{DOCS_BASE}/reference/spiders#forgejo",
        "actions": {
            "weave": "Запустить сборку и собрать произведённые артефакты.",
        },
        "inputs": {
            "repo": {"required": True, "description": "Имя репозитория Forgejo."},
            "workflow": {"required": True, "description": "Файл workflow, например build.yaml."},
            "owner": {"default": "FORGEJO_OWNER", "description": "Владелец/организация репозитория. Обычно можно не указывать."},
            "ref": {"default": "main", "description": "Git ref или ветка, на которой запускается workflow."},
            "branch": {"description": "Псевдоним для ref. Используйте только если так понятнее в конкретном сценарии."},
            "component": {"description": "Логическое имя компонента для логов и метаданных."},
            "version": {"description": "Версия, передаваемая workflow как input."},
        },
        "example": """- id: build-client\n  spider: forgejo\n  action: weave\n  with:\n    repo: redvrm-client\n    workflow: build.yaml\n    ref: \"${params.branch}\"\n    version: \"${params.version}\"""",
    },
    "gitlab": {
        "description": "Запускает GitLab CI pipeline и собирает job logs и artifacts.",
        "docs_url": f"{DOCS_BASE}/reference/spiders#gitlab",
        "actions": {
            "weave": "Запустить GitLab pipeline как Weave-операцию.",
        },
        "inputs": {
            "project": {"required": True, "description": "GitLab project path, например platform/backend."},
            "repo": {"description": "Псевдоним для project."},
            "ref": {"default": "main", "description": "Ветка или ref для pipeline."},
            "branch": {"description": "Псевдоним для ref."},
            "component": {"description": "Логическое имя компонента."},
        },
        "example": """- id: build-backend\n  spider: gitlab\n  action: weave\n  with:\n    project: platform/backend\n    ref: main\n    version: \"${params.version}\"""",
    },
    "ansible-local": {
        "description": "Выполняет ansible-playbook локально. Может принимать Brood artifact целиком как target.",
        "docs_url": f"{DOCS_BASE}/reference/spiders#ansible-local",
        "actions": {
            "command": "Выполнить playbook над целевой машиной или окружением.",
        },
        "inputs": {
            "playbook": {"description": "Путь к playbook. Если не указан, может быть выведен из component."},
            "component": {"description": "Компонент, над которым выполняется команда."},
            "target": {"description": "Рекомендуется передавать Brood artifact: ${stand.artifact}. Явный hostname/IP тоже поддерживается."},
            "os": {"description": "ОС target. Обычно берётся из Brood artifact и вручную не нужна."},
            "version": {"description": "Версия пакета/продукта для playbook."},
        },
        "example": """- id: deploy\n  spider: ansible-local\n  action: command\n  with:\n    target: \"${stand.artifact}\"\n    playbook: install-redvrm.yml\n    version: \"${params.version}\"""",
    },
    "tofu-proxmox": {
        "description": "Создаёт эфемерный стенд из Golden Image или уничтожает ранее созданный стенд.",
        "docs_url": f"{DOCS_BASE}/operations/proxmox-opentofu",
        "actions": {
            "brood": "Создать виртуальную машину и вернуть стандартный Brood Target artifact.",
            "destroy": "Уничтожить ранее созданную машину и её OpenTofu state.",
        },
        "inputs": {
            "name": {"default": "test-stand", "description": "Уникальное имя стенда/VM."},
            "os": {
                "default": "redos8",
                "options": ["redos7", "redos8", "windows"],
                "description": "Семейство ОС. Если image не задан, одновременно используется как ключ Golden Image profile.",
            },
            "image": {"description": "Golden Image profile. Нужен, если для одной ОС заведено несколько профилей."},
            "lifetime": {"description": "Сколько жить стенду до автоматического cleanup: например 30m, 2h или 1d."},
            "resources": {"description": "Необязательные overrides: cpu, memory_gb, disk_gb. Неуказанные значения наследуются от Golden Image."},
        },
        "example": """- id: stand\n  spider: tofu-proxmox\n  action: brood\n  with:\n    name: test-${params.version}\n    os: redos8\n    lifetime: 30m\n    resources:\n      cpu: 4\n      memory_gb: 8""",
    },
    "ansible-ovirt": {
        "description": "Создаёт oVirt VM через коллекцию ovirt.ovirt и возвращает Brood Target.",
        "docs_url": f"{DOCS_BASE}/reference/spiders#ansible-ovirt",
        "actions": {
            "brood": "Создать виртуальную машину в oVirt.",
        },
        "inputs": {
            "name": {"default": "test-stand", "description": "Имя создаваемой VM."},
            "os": {"default": "redos8", "options": ["redos7", "redos8", "windows"], "description": "Семейство гостевой ОС."},
        },
        "example": """- id: stand\n  spider: ansible-ovirt\n  action: brood\n  with:\n    name: test-001\n    os: redos8""",
    },
    "scenario": {
        "description": "Запускает другой сценарий Arachne как дочерний шаг и ждёт его завершения.",
        "docs_url": f"{DOCS_BASE}/reference/scenario-syntax#запуск-другого-сценария",
        "actions": {
            "command": "Запустить дочерний сценарий как оркестрационную команду.",
        },
        "inputs": {
            "scenario": {"required": True, "description": "Slug опубликованного дочернего сценария."},
            "params": {"description": "Mapping параметров, передаваемых дочернему сценарию."},
        },
        "example": """- id: child\n  spider: scenario\n  action: command\n  with:\n    scenario: smoke-test\n    params:\n      target: \"${stand.artifact}\"""",
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

        family = getattr(spider, "FAMILY", "weave")
        actions = contract.get("actions") or {family: f"Run {family} operation."}
        spiders.append({
            "name": name,
            "family": family,
            "description": contract.get("description", "Установленный spider без расширенной справки."),
            "docs_url": contract.get("docs_url", f"{DOCS_BASE}/reference/spiders"),
            "actions": list(actions),
            "action_help": actions,
            "inputs": contract.get("inputs", {}),
            "example": contract.get("example", ""),
        })

    return {
        "spiders": spiders,
        "families": ["weave", "brood", "command"],
        "family_help": {
            "weave": "Создание build artifacts: пакетов, инсталляторов, архивов и других результатов сборки.",
            "brood": "Создание вычислительных окружений и машин.",
            "command": "Действия над уже существующими окружениями или запуск оркестрационных операций.",
        },
        "docs_url": f"{DOCS_BASE}/reference/scenario-syntax",
        "triggers": sorted(all_triggers()),
        "param_types": ["string", "choice", "boolean"],
    }
