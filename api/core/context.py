"""RunContext accumulates step outputs and resolves ${...} references.

Reference forms:
    ${params.X}            scenario input
    ${<step_id>.<field>}   field from a prior step's primary artifact
    ${<step_id>.artifact}  the whole primary artifact object

Resolution is recursive for mappings and lists. A value consisting solely of one
reference preserves the referenced Python type; references embedded into a larger
string are converted to text.
"""
from __future__ import annotations

import re
from typing import Any

from core.types import StepResult

_REF = re.compile(r"\$\{([a-zA-Z0-9_\-]+)\.([a-zA-Z0-9_\-]+)\}")
_UNRESOLVED = re.compile(r"\$\{[^{}]+\}")


class RunContext:
    def __init__(self, params: dict, *, user_id: int | None = None):
        self.params = params
        # Internal execution metadata is deliberately separate from params so it
        # cannot be referenced from scenario DSL as ${params.__user_id__}.
        self.user_id = user_id
        self.steps: dict[str, StepResult] = {}

    def record(self, result: StepResult):
        self.steps[result.step_id] = result

    # ---- resolution ----
    def _lookup(self, ns: str, key: str):
        if ns == "params":
            if key not in self.params:
                raise KeyError(f"unknown parameter reference '${{{ns}.{key}}}'")
            return self.params[key]

        result = self.steps.get(ns)
        if not result:
            raise KeyError(f"unknown step reference '${{{ns}.{key}}}'")
        art = result.primary
        if art is None:
            return None
        return art.field_value(key)

    def resolve_scalar(self, value):
        """Resolve references in one scalar value.

        If the entire string is one reference, preserve the referenced type. If
        references are embedded in text, stringify their values. Any remaining
        `${...}` token is rejected instead of leaking silently to a spider.
        """
        if not isinstance(value, str):
            return value

        full = _REF.fullmatch(value.strip())
        if full:
            return self._lookup(full.group(1), full.group(2))

        def _sub(match):
            resolved = self._lookup(match.group(1), match.group(2))
            return "" if resolved is None else str(resolved)

        resolved = _REF.sub(_sub, value)
        unresolved = _UNRESOLVED.search(resolved)
        if unresolved:
            raise ValueError(f"unsupported or malformed reference '{unresolved.group(0)}'")
        return resolved

    def resolve(self, value: Any):
        """Recursively resolve references at arbitrary mapping/list depth."""
        if isinstance(value, dict):
            return {key: self.resolve(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self.resolve(item) for item in value]
        return self.resolve_scalar(value)

    def resolve_dict(self, d: dict) -> dict:
        """Compatibility entrypoint for step `with` mappings."""
        return self.resolve(d)
