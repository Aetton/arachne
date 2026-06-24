"""Plugin registries. Plugins self-register on import; the loader imports every
module under plugins/<kind>/ so dropping a file in is enough to enable it."""
from __future__ import annotations

import importlib
import pkgutil
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.spider import BaseSpider
    from core.trigger import BaseTrigger

_spiders: dict[str, "BaseSpider"] = {}
_triggers: dict[str, type["BaseTrigger"]] = {}


def register_spider(spider: "BaseSpider"):
    _spiders[spider.NAME] = spider
    return spider


def get_spider(name: str) -> "BaseSpider":
    if name not in _spiders:
        raise KeyError(f"spider '{name}' not registered; have {sorted(_spiders)}")
    return _spiders[name]


def all_spiders() -> dict[str, "BaseSpider"]:
    return dict(_spiders)


def register_trigger(cls: type["BaseTrigger"]):
    _triggers[cls.NAME] = cls
    return cls


def get_trigger(name: str) -> type["BaseTrigger"]:
    if name not in _triggers:
        raise KeyError(f"trigger '{name}' not registered; have {sorted(_triggers)}")
    return _triggers[name]


def all_triggers() -> dict[str, type["BaseTrigger"]]:
    return dict(_triggers)


def load_plugins(package: str = "plugins"):
    """Import every submodule under plugins/* so registrations fire."""
    pkg = importlib.import_module(package)
    for _, modname, ispkg in pkgutil.iter_modules(pkg.__path__):
        sub = f"{package}.{modname}"
        if ispkg:
            load_plugins(sub)
        else:
            importlib.import_module(sub)
