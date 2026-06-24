"""Chain trigger — fire this scenario when another finishes with a given status.

    triggers:
      - {type: chain, after: build-nightly, on: success}

Per-scenario granularity (run B after scenario A completes). Subscribes to the
run-completion event bus; the core never imports this plugin directly.
"""
from __future__ import annotations

from core import events
from core.trigger import BaseTrigger
from core.registry import register_trigger


@register_trigger
class ChainTrigger(BaseTrigger):
    NAME = "chain"

    def setup(self, scenario_key: str, cfg: dict) -> None:
        after = cfg.get("after")
        on = cfg.get("on", "success")
        if not after:
            return

        def _on_complete(payload: dict):
            if payload.get("scenario") == after and payload.get("status") == on:
                # fire downstream scenario with empty params (defaults apply)
                self.fire(scenario_key, {}, source=f"chain:{after}")

        events.subscribe(events.RUN_COMPLETED, _on_complete)
