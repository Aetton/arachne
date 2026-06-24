"""Trigger contract. A trigger starts a run of a scenario when its condition is
met. It calls orchestrator.fire(...) — injected at setup to avoid import cycles."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Callable

# fire(scenario_key: str, params: dict, source: str) -> str(run_id)
FireFn = Callable[[str, dict, str], str]


class BaseTrigger(ABC):
    NAME: str = "base"

    def __init__(self, fire: FireFn):
        self.fire = fire

    @abstractmethod
    def setup(self, scenario_key: str, cfg: dict) -> None:
        """Wire up the trigger for one scenario (subscribe, schedule, etc.)."""
        ...

    def teardown(self) -> None:
        """Optional: undo setup (unschedule, unsubscribe)."""
        return None
