"""Preserve bounded scientific author findings when paper preparation is rejected."""

from __future__ import annotations

import copy
from typing import Any


class PaperAcceptanceError(RuntimeError):
    """Executor preparation failure retains the exact fresh gate, never acceptance."""

    def __init__(self, gate: dict[str, Any]) -> None:
        if gate.get("accepted"):
            raise ValueError("A passing paper gate cannot create a rejection error")
        self.details = copy.deepcopy(gate.get("details") or {})
        super().__init__("Staged manuscript did not satisfy the quality contract: "
                         + str(gate.get("summary") or gate.get("reason") or "unknown failure"))

    def gate_details(self) -> dict[str, Any]:
        """Typed stage IDs and legal targets remain intact across the outer revision loop."""
        return copy.deepcopy(self.details)
