"""Non-model preflight for the authorized full workflow; never grants acceptance."""

import argparse
import json
from pathlib import Path
import sys
import tempfile

REPOSITORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY))


def main() -> int:
    from scripts.verify_full_benchmark_workflow import copy_independent_project
    from scripts.full_benchmark_preparation import prepare_stage_targets, refresh_current_authority
    from scripts.full_benchmark_scope import numerical_fingerprint, tree_hashes
    from server.services.frozen_benchmark_authority import historical_inputs_digest, benchmark_inventory_digest
    from server.services.experiment_implementation import experiment_implementation_service
    from server.services.experiment_implementation_build import experiment_implementation_build_service
    from server.services.planned_result_reuse import resolve_planned_result_reuse
    from server.services.method_contract import method_contract_service
    from server.services.experiment_placeholder_context import input_bundle_sha256
    from server.utils.atomic_write import atomic_write_json

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--original", type=Path, required=True)
    parser.add_argument("--reference", type=Path, required=True)
    options = parser.parse_args()
    source, original, reference = (path.resolve(strict=True) for path in (options.source, options.original, options.reference))
    before = [tree_hashes(root) for root in (source, original, reference)]
    root = Path(tempfile.mkdtemp(prefix="full-benchmark-verification-preflight-", dir=REPOSITORY))
    copy_independent_project(source, root)
    numerical = numerical_fingerprint(root)
    config = json.loads((original / ".merak/runs/3de990b9ec00.json").read_text(encoding="utf-8-sig"))["config"]
    settings = {"direction": config["direction"], "evidence_mode": "synthetic_preview",
        "target_venue": config["options"].get("target_venue", ""), "research_family": config["options"].get("research_family", ""),
        "study_archetype": config["options"].get("study_archetype", "")}
    context = {"schema": 1, "historical_inputs_root": str(original), "frozen_reference_root": str(reference),
        "historical_inputs_pin": historical_inputs_digest(original, settings),
        "benchmark_inventory_pin": benchmark_inventory_digest(reference), "settings": settings, "prospective_inventory_pin": ""}
    prepare_stage_targets(root)
    context = refresh_current_authority(root, context)
    digest = input_bundle_sha256(root, settings["direction"], **{name:value for name,value in settings.items() if name != "direction"})
    reused, _manifest = resolve_planned_result_reuse(root, [root / "experiments/results/templates/PLANNED_RESULT_MANIFEST.json"],
        mode="synthetic_preview", input_hash=digest, target_venue=settings["target_venue"], force=False, frozen_authority=context)
    implementation = experiment_implementation_service.audit(root)
    stages = [experiment_implementation_build_service.validate_stage(root, stage.id, settings["direction"])
              for stage in experiment_implementation_build_service.stages(root, settings["direction"])]
    selected = json.loads((root / "ideas/SELECTED_IDEA.json").read_text(encoding="utf-8-sig"))
    method = method_contract_service.validate_method_contract(root, selected["title"])
    result = {"root": str(root), "models_invoked": False, "training_performed": False,
        "benchmark_regenerated": reused, "implementation_audit": implementation,
        "method_valid": method[0], "method_issues": method[1], "stage_validations": stages,
        "authority_context": context, "current_input_sha256": digest,
        "source_inputs_unchanged": before == [tree_hashes(path) for path in (source, original, reference)],
        "numerical_evidence_unchanged": numerical == numerical_fingerprint(root), "workflow_acceptance_granted": False}
    atomic_write_json(root / "FULL_PREFLIGHT_REPORT.json", result)
    print(json.dumps(result, ensure_ascii=False), flush=True)
    return int(result["benchmark_regenerated"] or not result["source_inputs_unchanged"] or not result["numerical_evidence_unchanged"])


if __name__ == "__main__":
    raise SystemExit(main())
