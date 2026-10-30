"""Explicit user-approved local reacceptance, without research models or training."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path


REPOSITORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY))


async def checked_reaccept(root: Path, original: Path, options: argparse.Namespace, offline: dict) -> dict:
    from scripts.live_snapshot_local_acceptance import reaccept_current_gates
    from scripts.live_snapshot_reaccept_identity import validate_invalidated_copy
    from scripts.live_snapshot_specialist_reuse import prepare_same_science_specialist_reuse
    from scripts.verify_live_remaining_snapshot import protected_inputs, validate_offline_receipt
    from server.utils.atomic_write import atomic_write_bytes, atomic_write_json

    science_before = protected_inputs(root)
    identity = validate_invalidated_copy(root, original, options.run_id, REPOSITORY,
        options.expected_scientific_sha256, options.expected_report_sha256,
        options.expected_source_trace_sha256, options.expected_state_sha256, science_before)
    plan_path = root / f".merak/runs/{options.run_id}.specialists.json"
    state_path = root / f".merak/runs/{options.run_id}.json"
    before_plan, before_state = plan_path.read_bytes(), state_path.read_bytes()
    manifest_before = {name: (root / "figures" / name).read_bytes() if (root / "figures" / name).exists() else None
                       for name in ("FIGURE_MANIFEST.json", "FIGURE_MANIFEST.md")}
    new_plan, reuse_proof = prepare_same_science_specialist_reuse(root, original, options.run_id)
    validate_offline_receipt(Path(offline["receipt_path"]))
    try:
        atomic_write_json(plan_path, new_plan)
        receipt = await reaccept_current_gates(root, options.run_id, options.expected_state_sha256)
        if protected_inputs(root) != science_before:
            raise ValueError("Scientific bytes changed during local reacceptance")
        receipt.update({"source_identity": identity, "specialist_reuse_proof": reuse_proof,
                        "offline_verification": offline, "training_authorized": False,
                        "original_workflow_resumed": False})
        archive = root / f".merak/transactions/local-reaccept-{options.expected_state_sha256}.specialists.original.json"
        if archive.exists() and archive.read_bytes() != before_plan:
            raise ValueError("Specialist transaction checkpoint conflicts with its original bytes")
        if not archive.exists():
            atomic_write_bytes(archive, before_plan)
        receipt["specialist_plan_before_sha256"] = hashlib.sha256(before_plan).hexdigest()
        receipt["specialist_plan_after_sha256"] = hashlib.sha256(plan_path.read_bytes()).hexdigest()
        receipt["specialist_plan_checkpoint"] = archive.relative_to(root).as_posix()
        atomic_write_json(root / ".merak/LOCAL_REACCEPT_REPORT.json", receipt)
        return receipt
    except BaseException:
        atomic_write_bytes(state_path, before_state)
        atomic_write_bytes(plan_path, before_plan)
        for name, content in manifest_before.items():
            target = root / "figures" / name
            if content is not None:
                atomic_write_bytes(target, content)
            elif target.exists():
                target.unlink()
        raise


async def _local_only(root: Path, original: Path, options: argparse.Namespace, offline: dict) -> dict:
    from scripts.local_acceptance_scope import local_reacceptance_scope
    # The Windows event loop creates its internal self-pipe before the scope;
    # every application operation, including imports and reuse proofs, is scoped.
    with local_reacceptance_scope():
        return await checked_reaccept(root, original, options, offline)


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("snapshot", "project", "offline-report"):
        parser.add_argument("--" + name, type=Path, required=True)
    for name in ("run-id", "expected-scientific-sha256", "expected-report-sha256",
                 "expected-source-trace-sha256", "expected-state-sha256"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--allow-local-reacceptance", action="store_true", required=True)
    return parser.parse_args()


def main() -> int:
    options = _arguments()
    from scripts.verify_live_remaining_snapshot import install_write_guard, validate_offline_receipt
    from scripts.live_snapshot_resume_validation import validate_copy_boundary

    offline = validate_offline_receipt(options.offline_report)
    root, original = options.snapshot.resolve(strict=True), options.project.resolve(strict=True)
    if root.parent != REPOSITORY or not root.name.startswith("live-verification-106-") or root == original:
        raise ValueError("Local reacceptance cannot target the source or an arbitrary workspace")
    validate_copy_boundary(root)
    os.chdir(root)
    os.environ.update({"PYTHONDONTWRITEBYTECODE": "1", "TEMP": str(root), "TMP": str(root),
                       "MPLCONFIGDIR": str(root / "matplotlib"), "MERAK_DISABLE_ELECTRON_RENDERER_DISCOVERY": "1"})
    os.environ.pop("MERAK_ELECTRON_API_PORT", None)
    tempfile.tempdir = str(root)
    install_write_guard(root)
    print(json.dumps({"snapshot_path": str(root), "local_reacceptance": True, "model_invoked": False}), flush=True)
    try:
        result = asyncio.run(_local_only(root, original, options, offline))
    except (ValueError, RuntimeError, OSError, KeyError) as error:
        print(json.dumps({"accepted": False, "issues": [f"{type(error).__name__}: {error}"]}), flush=True)
        return 1
    print(json.dumps({"accepted": result["accepted"], "nodes": result["reaccepted_nodes"],
                      "state_sha256": result["state_after_sha256"], "model_invoked": False}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
