"""Prepare explicit current-code targets and separate historical benchmark authority.

Only a new independent verification copy is written. Scientific results and
prior verdicts stay immutable; current negative readiness is not upgraded.
"""

from __future__ import annotations

import json
import hashlib
from pathlib import Path

from server.utils.atomic_write import atomic_write_json, path_lock
from server.services.frozen_benchmark_authority import prospective_inventory_digest
from server.services.frozen_benchmark_runtime import commit_authority
from server.services.protocol_conformance import build_protocol_conformance_ledger
from server.services.experiment_placeholder_context import input_bundle_sha256


def stage_target_declarations() -> dict[str, list[str]]:
    prefix = "experiments/src/csfs_v1/"
    return {
        "data": [prefix + name for name in ("data.py", "data_contract.py", "preprocessing.py", "perturbations.py")],
        "method": [prefix + name for name in ("models.py", "objectives.py", "baselines.py", "capacity.py")],
        "training": [prefix + name for name in ("training.py", "training_policy.py", "training_state.py", "study.py")],
        "evaluation": [prefix + name for name in ("metrics.py", "statistics.py", "evaluation.py", "execution_io.py",
                                                   "execution_safety.py", "checkpoint_contract.py", "persistence.py")],
        "integration": ["experiments/src/train.py", prefix + "cli.py", prefix + "protocol.py",
                        "experiments/IMPLEMENTATION_EVIDENCE_PATCH.json", "experiments/RUN_SPEC.json",
                        "experiments/configs/main.yaml"],
    }


def prepare_stage_targets(root: Path) -> None:
    """Declare actual package paths; do not recreate nonexistent historical aliases."""
    path = root / "experiments/RUN_SPEC.json"
    with path_lock(path):
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
        if payload.get("protocol_id") != "CSFS-v1" or payload.get("run_experiment_authorized") is not False:
            raise ValueError("Package stage mapping is restricted to the approved nonexecuted CSFS implementation")
        payload["implementation_stage_targets"] = stage_target_declarations()
        atomic_write_json(path, payload)
    patch_path = root / "experiments/IMPLEMENTATION_EVIDENCE_PATCH.json"
    if patch_path.is_file():
        from server.utils.atomic_write import atomic_write_bytes

        archive = root / ".merak/source-evidence/implementation-evidence-patch.original.json"
        if not archive.exists():
            atomic_write_bytes(archive, patch_path.read_bytes())
    method = json.loads((root / "experiments/METHOD_CONTRACT.json").read_text(encoding="utf-8-sig"))
    coverage = {row["id"]: [item["idea_mechanism_id"] for item in method["mechanism_coverage"]
                          if row["id"] in item.get("implementation_check_ids", [])] for row in method["implementation_checks"]}
    checks = [{"check_id": row["id"], "description": row["description"], "evidence": row["evidence"],
               "idea_mechanism_ids": coverage[row["id"]]} for row in method["implementation_checks"]]
    atomic_write_json(patch_path, {"schema": 1, "checks": checks})


def refresh_current_authority(root: Path, context: dict) -> dict:
    """Commit a producer-owned current context; historical data/source pins remain fixed."""
    _bind_current_scene_sources(root)
    readiness_path = root / "experiments/PROTOCOL_CONFORMANCE.json"
    old = json.loads(readiness_path.read_text(encoding="utf-8-sig"))
    if (old.get("cannot_execute") is not True or old.get("research_evidence") is not False
            or any(row.get("status") not in {"corrected_locally", "unvalidated"} for row in old.get("findings") or [])):
        raise ValueError("A workflow context refresh cannot erase unresolved scientific readiness findings")
    readiness = build_protocol_conformance_ledger(root, old["findings"])
    atomic_write_json(readiness_path, readiness)
    current = {**context, "prospective_inventory_pin": prospective_inventory_digest(root)}
    settings = current["settings"]
    digest = input_bundle_sha256(root, settings["direction"],
        **{name: value for name, value in settings.items() if name != "direction"})
    commit_authority(root, current, digest)
    return current


def _bind_current_scene_sources(root: Path) -> None:
    """Code owns source hashes, while the design author still owns scene semantics."""
    from server.services.scientific_scene import validate_scientific_scene

    path = root / "experiments/METHOD_CONTRACT.json"
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    scene = payload.get("scientific_scene")
    issues = validate_scientific_scene(scene)
    if issues:
        raise ValueError("Current design scene has unresolved scientific defects: " + "; ".join(issues[:8]))
    changed = False
    for node in scene["objects"]:
        relative = node["source_path"]
        target = (root / relative).resolve()
        if (not target.is_relative_to(root) or not target.is_file() or target.is_symlink()
                or not (relative in {"ideas/SELECTED_IDEA.json", "experiments/EXPERIMENT_PLAN.md"}
                        or relative.startswith("experiments/src/"))):
            raise ValueError("Scientific scene refers to a missing, foreign or undeclared source")
        digest = hashlib.sha256(target.read_bytes()).hexdigest()
        if node.get("source_sha256") != digest:
            node["source_sha256"], changed = digest, True
    if changed:
        atomic_write_json(path, payload)


class CurrentBenchmarkPreparation:
    """Bind owner-produced context before a consumer, without changing any gate."""

    def __init__(self, host, root: Path, context: dict, *, staged_implementation=None):
        self.root, self.context = root, dict(context)
        self.original = host._ensure_planned_result_templates
        self.staged_implementation = staged_implementation

    async def integrate(self, *, run, direction: str, opts: dict) -> dict:
        """Bind authored scene sources before any implementation input is recorded.

        Delegation retains the real stage validator and its verdict ownership.
        A foreign run, execution request or invalid scene fails before that
        handler starts; a later evidence consumer cannot repair accepted hashes.
        """
        if (Path(run.project_path).resolve() != self.root
                or run.options.get("run_experiment") is True or opts.get("run_experiment") is True):
            raise ValueError("Frozen benchmark integration cannot enter another project or execute research")
        if self.staged_implementation is None:
            raise ValueError("Frozen benchmark integration requires its original staged producer")
        _bind_current_scene_sources(self.root)
        return await self.staged_implementation(run=run, direction=direction, opts=opts)

    async def ensure(self, run, direction: str, force: bool = False):
        if Path(run.project_path).resolve() != self.root or run.options.get("run_experiment") is True or force:
            raise ValueError("Frozen benchmark preparation cannot enter another project or regenerate evidence")
        current = refresh_current_authority(self.root, self.context)
        run.options["frozen_benchmark_authority"] = current
        self.context = current
        result = await self.original(run, direction, force=False)
        run.options.setdefault("_benchmark_scope_proofs", []).append({
            "prospective_inventory_pin": current["prospective_inventory_pin"],
            "historical_inputs_pin": current["historical_inputs_pin"],
            "benchmark_inventory_pin": current["benchmark_inventory_pin"],
            "workflow_acceptance_granted": False,
        })
        return result
