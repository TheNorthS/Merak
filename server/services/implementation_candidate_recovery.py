"""Runtime-owned evidence merge/finalization, identical after restart or a model turn."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..contracts.implementation_evidence import parse_evidence_patch_document
from ..utils.atomic_write import atomic_write_bytes, path_lock
from .implementation_stage_validation import integration_candidate_report
from .method_contract import method_contract_service
from .method_contract_persistence import apply_implementation_evidence_patches


def recover_integration_candidate(service: Any, root: Path, direction: str) -> dict[str, Any]:
    """Commit only a freshly validated existing candidate; preserve rejected bytes.

    No source or scientific choice is authored here. The original model evidence
    patch is checked against the accepted idea by the same merge boundary used
    after model execution. Missing evidence and scientific blockers cannot grant
    an implemented status, even after a process interruption.
    """
    method_path = root / "experiments/METHOD_CONTRACT.json"
    with path_lock(method_path):
        original = method_path.read_bytes()
        committed = False
        try:
            patch_path = root / "experiments/IMPLEMENTATION_EVIDENCE_PATCH.json"
            patches = parse_evidence_patch_document(json.loads(patch_path.read_text(encoding="utf-8-sig")))
            apply_implementation_evidence_patches(method_path, patches)
            report = service.validate_stage(root, "integration", direction)
            candidate = integration_candidate_report(report)
            if not candidate.get("passed"):
                return report
            if not method_contract_service.finalize_integration_contract(root, candidate):
                return {**report, "passed": False, "issues": ["integration runtime finalization did not commit"]}
            fresh = service.validate_stage(root, "integration", direction)
            committed = bool(fresh.get("passed"))
            return fresh
        finally:
            if not committed and method_path.read_bytes() != original:
                atomic_write_bytes(method_path, original)
