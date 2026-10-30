"""Continue the same user-authorized isolated real verification; never its source."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path


REPOSITORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY))


async def continue_verified(root: Path, original: Path, run_id: str, offline: Path,
                            pinned: str, report_pin: str, trace_pin: str, local_receipt_pin: str = "",
                            progress_state_pin: str = "", progress_trace_pin: str = "") -> dict:
    from scripts.verify_live_remaining_snapshot import (
        install_write_guard, protected_inputs, run_remaining, validate_offline_receipt,
    )
    from scripts.live_snapshot_resume_validation import validate_resume_identity
    from scripts.live_snapshot_safety import load_current_model_config_readonly
    from server.agent import init_models_from_config, model_router
    from server.agent.tools import register_all_tools
    from server.services.skill_registry import skill_registry

    before = protected_inputs(root)
    if progress_state_pin or progress_trace_pin:
        if not local_receipt_pin or not progress_state_pin or not progress_trace_pin:
            raise ValueError("Interrupted continuation requires both observed progress pins and its local receipt")
        from scripts.live_snapshot_progress_validation import validate_authorized_progress
        identity = validate_authorized_progress(root, original, run_id, local_receipt_pin,
            progress_state_pin, progress_trace_pin, pinned, trace_pin, report_pin)
    else:
        identity = validate_resume_identity(root, original, run_id, pinned, report_pin, trace_pin,
                                            before, REPOSITORY, local_receipt_pin)
    install_write_guard(root)
    validate_offline_receipt(offline)
    config = load_current_model_config_readonly(REPOSITORY)
    init_models_from_config(config)
    if not model_router._providers:
        raise RuntimeError("No configured provider is available for authorized verification continuation")
    skill_registry.scan_directory(str(REPOSITORY / "merak-skills"))
    register_all_tools()
    validate_offline_receipt(offline)
    result = await run_remaining(root, run_id)
    result.update({"scientific_inputs_unchanged": before == protected_inputs(root),
                   "real_model_execution": True, "training_authorized": False,
                   "original_workflow_resumed": False, "continuation_identity": identity})
    result["accepted"] = result["accepted"] and result["scientific_inputs_unchanged"]
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--offline-report", type=Path, required=True)
    parser.add_argument("--expected-scientific-sha256", required=True)
    parser.add_argument("--expected-report-sha256", required=True)
    parser.add_argument("--expected-source-trace-sha256", required=True)
    parser.add_argument("--local-reacceptance-report-sha256", default="")
    parser.add_argument("--progress-state-sha256", default="")
    parser.add_argument("--progress-trace-sha256", default="")
    parser.add_argument("--allow-real-models", action="store_true", required=True)
    parser.add_argument("--allow-narrative-revalidation", action="store_true", required=True)
    options = parser.parse_args()
    from scripts.verify_live_remaining_snapshot import validate_offline_receipt
    offline = validate_offline_receipt(options.offline_report)
    root, original = options.snapshot.resolve(strict=True), options.project.resolve(strict=True)
    if root.parent != REPOSITORY or not root.name.startswith("live-verification-106-") or root == original:
        raise ValueError("Continuation cannot write a source project or an arbitrary workspace")
    from scripts.live_snapshot_resume_validation import validate_copy_boundary
    from scripts.verify_live_remaining_snapshot import install_write_guard
    validate_copy_boundary(root)
    os.chdir(root)
    os.environ.update({"MERAK_SKILLS_PATH": str(REPOSITORY / "merak-skills"),
                       "MERAK_DISABLE_ELECTRON_RENDERER_DISCOVERY": "1", "PYTHONDONTWRITEBYTECODE": "1",
                       "TEMP": str(root), "TMP": str(root), "MPLCONFIGDIR": str(root / "matplotlib"),
                       "openout_any": "p", "shell_escape": "f"})
    os.environ.pop("MERAK_ELECTRON_API_PORT", None)
    tempfile.tempdir = str(root)
    install_write_guard(root)
    from scripts.verify_paper_preparation_snapshot import files
    from scripts.live_snapshot_copy import additional_input_files, safe_selected_input_files
    from scripts.verify_figure_snapshot import hashes
    from server.utils.atomic_write import atomic_write_json
    selected = safe_selected_input_files(original, [*files(original), *additional_input_files(original, options.run_id)])
    original_before = hashes(selected, original)
    print(json.dumps({"snapshot_path": str(root), "continuation": True, "training": False}), flush=True)
    try:
        result = asyncio.run(continue_verified(root, original, options.run_id, Path(offline["receipt_path"]),
                                              options.expected_scientific_sha256, options.expected_report_sha256,
                                              options.expected_source_trace_sha256,
                                              options.local_reacceptance_report_sha256,
                                              options.progress_state_sha256, options.progress_trace_sha256))
    except (RuntimeError, ValueError, OSError, KeyError) as error:
        print(json.dumps({"accepted": False, "issues": [f"{type(error).__name__}: {error}"]}), flush=True)
        return 1
    result.update({"snapshot_path": str(root), "original_inputs_unchanged": original_before == hashes(selected, original),
                   "offline_verification": offline})
    result["accepted"] = result["accepted"] and result["original_inputs_unchanged"]
    atomic_write_json(root / ".merak/LIVE_CONTINUATION_REPORT.json", result)
    print(json.dumps(result, ensure_ascii=False), flush=True)
    return 0 if result["accepted"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
