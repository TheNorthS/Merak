"""Asset-scoped deterministic failures retain ownership through workflow gates."""

from __future__ import annotations

import hashlib
from typing import Any


class DeterministicFigureProducerError(RuntimeError):
    """A failed deterministic asset remains blocking and has an exact repair scope."""

    def __init__(self, message: str, *, findings: list[dict[str, Any]] | None = None) -> None:
        super().__init__(message)
        self.findings = [dict(item) for item in findings or []]

    def with_asset(self, identity: str, strategy: str) -> "DeterministicFigureProducerError":
        if self.findings:
            return self
        digest = hashlib.sha256(f"{identity}:{self}".encode("utf-8")).hexdigest()[:12]
        directory, extension = {
            "deterministic_architecture": ("diagrams", "json"),
            "deterministic_template": ("diagrams", "svg"),
            "deterministic_plot": ("plots", "py"),
        }.get(strategy, ("diagrams", "svg"))
        finding = {
            "id": f"FIGURE-PRODUCER-{identity}-{digest}", "severity": "blocker",
            "category": "figure_producer", "owner_node": "figure",
            "producer_kind": "deterministic", "asset_ids": [identity],
            "target_files": [f"figures/{directory}/{identity}.{extension}", "figures/FIGURE_SPECS.json"],
            "message": str(self), "plain_message": f"{identity} 的确定性生产器未通过：{self}",
            "remediation": "Repair this deterministic producer or its source-bound specification; do not invoke a model to rewrite sibling assets.",
        }
        return type(self)(str(self), findings=[finding])

    def gate_details(self) -> dict[str, Any]:
        return {
            "issues": [str(item["message"]) for item in self.findings] or [str(self)],
            "findings": self.findings,
            "repair_scope": {
                "asset_ids": list(dict.fromkeys(value for item in self.findings for value in item["asset_ids"])),
                "target_files": list(dict.fromkeys(value for item in self.findings for value in item["target_files"])),
            },
            "error_category": "figure_retry_deferred" if isinstance(self, UnchangedDeterministicFigureDefect) else "figure_producer",
        }


class UnchangedDeterministicFigureDefect(DeterministicFigureProducerError):
    """An unchanged failed deterministic producer is not a new render attempt."""


def aggregate_producer_failures(errors: list[DeterministicFigureProducerError]) -> DeterministicFigureProducerError:
    if len(errors) == 1:
        return errors[0]
    kind = UnchangedDeterministicFigureDefect if all(isinstance(error, UnchangedDeterministicFigureDefect) for error in errors) else DeterministicFigureProducerError
    return kind(
        "Deterministic figure assets failed: " + "; ".join(str(error) for error in errors),
        findings=[item for error in errors for item in error.findings],
    )
