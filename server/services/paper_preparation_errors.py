"""Structured failures of deterministic manuscript preparation, not authoring.

Only the producer can repair runtime-generated tables/contracts. These errors
retain exact artifact/cell scope and never claim that a model invocation ran or
that the manuscript has passed acceptance.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Callable, TypeVar


Result = TypeVar("Result")


class PaperPreparationError(RuntimeError):
    """A deterministic preparation operation failed before its model boundary."""

    def __init__(self, operation: str, cause: ValueError) -> None:
        self.operation = operation
        self.cause_type = type(cause).__name__
        label = str(getattr(cause, "table_label", "") or "")
        identity = label.removeprefix("tab:").replace("-", "_")
        safe_table = identity and all(char.isalnum() or char == "_" for char in identity)
        self.targets = ([f"paper/tables/{identity}.csv", f"paper/tables/{identity}.tex",
                         "paper/tables/TABLE_MANIFEST.json"] if safe_table else
                        ["paper/tables/TABLE_MANIFEST.json"] if operation == "table_evidence" else
                        ["paper/SECTION_CONTRACTS.json", "paper/DRAFT_STATE.json"])
        self.location = {"table_label": label, "row_index": getattr(cause, "row_index", None),
                         "column_key": str(getattr(cause, "column_key", "") or "")}
        super().__init__(f"Paper preparation failed at {operation}: {cause}")

    def gate_details(self) -> dict[str, Any]:
        identity = hashlib.sha256(f"{self}:{self.location}".encode("utf-8")).hexdigest()[:16]
        finding = {
            "id": f"PAPER-PREPARATION-{identity}", "severity": "blocker",
            "category": "paper_preparation", "owner_node": "paper",
            "producer_kind": "deterministic", "repair_capability": "platform_runtime",
            "message": str(self), "plain_message": str(self),
            "target_files": self.targets, "asset_ids": [],
            "validator": self.operation, "location": self.location,
            "remediation": "Repair the deterministic preparation producer; preserve accepted science and manuscript sections. Do not ask a model to rebind hashes or overwrite generated tables.",
        }
        return {"issues": [str(self)], "findings": [finding],
                "repair_scope": {"finding_ids": [finding["id"]], "target_files": self.targets, "asset_ids": []},
                "error_category": "paper_preparation", "retryable": False}


def guard_paper_preparation(operation: str, action: Callable[[], Result]) -> Result:
    """Translate deterministic validation errors only; programming/security faults propagate."""
    try:
        return action()
    except PaperPreparationError:
        raise
    except ValueError as error:
        raise PaperPreparationError(operation, error) from error


def prepare_paper_evidence(project_path: str | Path, direction: str = "") -> Any:
    from .paper_artifacts import paper_artifact_builder

    return guard_paper_preparation(
        "table_evidence", lambda: paper_artifact_builder.prepare(project_path, direction),
    )
