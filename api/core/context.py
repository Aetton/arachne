"""RunContext accumulates step outputs and resolves ${...} references.

Reference forms:
    ${params.X}            scenario input
    ${<step_id>.<field>}   field from a prior step's primary artifact
    ${<step_id>.artifact}  the whole primary artifact object
"""
from __future__ import annotations

import re

from core.types import StepResult, Artifact

_REF = re.compile(r"\$\{([a-zA-Z0-9_\-]+)\.([a-zA-Z0-9_\-]+)\}")


class RunContext:
    def __init__(self, params: dict):
        self.params = params
        self.steps: dict[str, StepResult] = {}

    def record(self, result: StepResult):
        self.steps[result.step_id] = result

    # ---- resolution ----
    def _lookup(self, ns: str, key: str):
        if ns == "params":
            return self.params.get(key)
        result = self.steps.get(ns)
        if not result:
            raise KeyError(f"unknown step reference '${{{ns}.{key}}}'")
        art = result.primary
        if art is None:
            return None
        return art.field_value(key)

    def resolve_scalar(self, value):
        """Resolve refs in a single value. If the whole string is one ref to an
        Artifact, return the Artifact object; else string-substitute."""
        if not isinstance(value, str):
            return value

        full = _REF.fullmatch(value.strip())
        if full:
            resolved = self._lookup(full.group(1), full.group(2))
            return resolved  # may be Artifact, bool, int, str...

        def _sub(m):
            r = self._lookup(m.group(1), m.group(2))
            return "" if r is None else str(r)

        return _REF.sub(_sub, value)

    def resolve_dict(self, d: dict) -> dict:
        out = {}
        for k, v in d.items():
            if isinstance(v, dict):
                out[k] = self.resolve_dict(v)
            elif isinstance(v, list):
                out[k] = [self.resolve_scalar(x) for x in v]
            else:
                out[k] = self.resolve_scalar(v)
        return out
