"""Manual trigger — the Run button. No background wiring; the HTTP route calls
fire() directly. This plugin exists so 'manual' is a known trigger type and the
UI knows to render a form."""
from __future__ import annotations

from core.trigger import BaseTrigger
from core.registry import register_trigger


@register_trigger
class ManualTrigger(BaseTrigger):
    NAME = "manual"

    def setup(self, scenario_key: str, cfg: dict) -> None:
        # nothing to wire; the dashboard renders the form + button
        return None
