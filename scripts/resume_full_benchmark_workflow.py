"""Explicitly continue one stopped full benchmark copy, never an original project.

This command requires real-model consent, exact observed report/state/trace
pins, the original independent benchmark pins, and a current whole-suite
offline receipt. It preserves scientific inputs and uses the existing run ID.
Importing the module does not start a workflow or contact a provider.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
import sys
import tempfile


REPOSITORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY))

from scripts.full_benchmark_continuation import prepare_continuation
from scripts.full_benchmark_continuation_scope import (
    validate_continuation_identity, validate_project_roots,
)
from scripts.full_benchmark_scope import PIPELINE_NODES, numerical_fingerprint, scientific_method_identity, tree_hashes
from scripts.verify_full_benchmark_workflow import _authority_context
from scripts.verify_live_remaining_snapshot import validate_offline_receipt


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("copy", "source", "original", "frozen-reference", "offline-report"):
        parser.add_argument("--" + name, type=Path, required=True)
    for name in ("run-id", "source-run-id", "historical-inputs-sha256", "benchmark-inventory-sha256",
                 "previous-report-sha256", "previous-state-sha256", "previous-trace-sha256"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--checkpoint-feedback", default="",
        help="Specific repair feedback; native per-asset retry/budget validation is unchanged")
    parser.add_argument("--operator-interruption-receipt-sha256", default="",
        help="Explicit observed non-accepting receipt for an operator-stopped private continuation")
    parser.add_argument("--natural-failure-receipt", type=Path,
        help="Explicit non-accepting observations of a naturally failed private prevalidation")
    parser.add_argument("--natural-failure-receipt-sha256", default="",
        help="Exact independently observed natural-failure receipt pin; no automatic history normalization")
    parser.add_argument("--allow-real-models", action="store_true", required=True)
    return parser


def _isolate_environment(root: Path) -> None:
    os.chdir(root)
    os.environ.update({"PYTHONDONTWRITEBYTECODE": "1", "MERAK_SKILLS_PATH": str(REPOSITORY / "merak-skills"),
        "MERAK_DISABLE_ELECTRON_RENDERER_DISCOVERY": "1", "MPLCONFIGDIR": str(root / ".mpl-cache"),
        "TEMP": str(root), "TMP": str(root), "openout_any": "p", "shell_escape": "f"})
    os.environ.pop("MERAK_ELECTRON_API_PORT", None)
    tempfile.tempdir = str(root)


def _failed_result(root: Path, run_id: str, identity: dict, error: BaseException) -> dict:
    from server.workflows.run_state import RunState
    from scripts.full_benchmark_failure import BenchmarkContinuationFailure, failure_observation

    state = RunState(str(root), run_id).load() or {}
    return {"run_id": run_id, "status": state.get("status"), "continuation": True, "accepted": False,
        "issues": [str(error) if isinstance(error, BenchmarkContinuationFailure) else f"{type(error).__name__}: {error}"],
        "phases": {name: phase.get("status") for name, phase in (state.get("phases") or {}).items()},
        "logical_pipeline_nodes": list(PIPELINE_NODES), "source_owner_reuse": {},
        "source_evidence": identity["previous_report"]["source_evidence"],
        "interruption_history": dict(identity.get("interruption_history") or {}),
        "natural_failure_history": dict(identity.get("natural_failure_history") or {}),
        "continuation_identity": {name: value for name, value in identity.items() if name.endswith("sha256")},
        "training_authorized": False, "real_model_execution": True, "original_workflow_resumed": False,
        **failure_observation(error)}


def _persist_report(root: Path, result: dict) -> int:
    """Print failures first so report I/O cannot hide the original diagnostic."""
    from server.utils.atomic_write import atomic_write_json

    print(json.dumps(result, ensure_ascii=False), flush=True)
    try:
        atomic_write_json(root / "FULL_BENCHMARK_REPORT.json", result)
    except OSError as error:
        print(json.dumps({"accepted": False, "report_persistence_error": f"{type(error).__name__}: {error}"}), flush=True)
        return 1
    return 0 if result["accepted"] else 1


def main() -> int:
    options = _parser().parse_args()
    offline = validate_offline_receipt(options.offline_report)
    root, source, original, reference = validate_project_roots(options.copy, options.source,
        options.original, options.frozen_reference, REPOSITORY)
    identity = validate_continuation_identity(root, source, original, options.run_id,
        options.source_run_id, options.previous_report_sha256, options.previous_state_sha256,
        options.previous_trace_sha256, reference=reference,
        operator_interruption_pin=options.operator_interruption_receipt_sha256,
        natural_failure_receipt=options.natural_failure_receipt,
        natural_failure_pin=options.natural_failure_receipt_sha256)
    authority = _authority_context(options, original, reference)
    immutable_roots = {path: tree_hashes(path) for path in (source, original, reference)}
    numerical_before, method_before = numerical_fingerprint(root), scientific_method_identity(root)
    from scripts.full_benchmark_continuation_scope import frozen_inputs

    inputs_before = frozen_inputs(root)
    _isolate_environment(root)
    print(json.dumps({"snapshot_path": str(root), "run_id": options.run_id,
        "continuation": True, "training_authorized": False}), flush=True)
    try:
        result = asyncio.run(prepare_continuation(root, options.run_id, Path(offline["receipt_path"]),
            authority, identity, options.checkpoint_feedback))
    except (RuntimeError, ValueError, OSError, KeyError) as error:
        result = _failed_result(root, options.run_id, identity, error)
    unchanged = all(before == tree_hashes(path) for path, before in immutable_roots.items())
    numerical_unchanged = numerical_before == numerical_fingerprint(root)
    science_unchanged = method_before == scientific_method_identity(root) and inputs_before == frozen_inputs(root)
    result.update({"snapshot_path": str(root), "offline_verification": offline, "originals_unchanged": unchanged,
        "originals_unchanged_scope": "current_continuation_only",
        "current_continuation_roots_unchanged": unchanged,
        "raw_numerical_and_semantic_bundle_unchanged": numerical_unchanged,
        "frozen_scientific_inputs_unchanged": science_unchanged})
    result["accepted"] = result["accepted"] and unchanged and numerical_unchanged and science_unchanged
    return _persist_report(root, result)


if __name__ == "__main__":
    raise SystemExit(main())
