"""Check real paper repair routing in a copy without invoking a model or compiler.

This verifies repair dispatch, not manuscript acceptance. Existing scientific
inputs and original execution traces remain unchanged; unresolved content gates
must remain visible. Model boundaries raise a sentinel before any paid request.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import sys
import tempfile
from contextlib import ExitStack, nullcontext
from pathlib import Path
from unittest.mock import patch
import copy


REPOSITORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY))

from scripts.verify_figure_snapshot import SnapshotEngine, hashes, snapshot_run
from scripts.verify_paper_preparation_snapshot import files
from server.services.paper_drafting import paper_drafting_service
from server.services.paper_artifacts import simulation_manifest_semantic_hash, simulation_manifest_semantic_payload
from server.services.node_risk_audit import node_risk_audit_service


class FirstRepairBoundary(BaseException):
    """Stop before model/tool invocation while retaining its legal write contract."""

    def __init__(self, skill: str, contract: str):
        self.skill = skill
        self.contract = contract


def _model_boundary(skill="unknown", *_args, **kwargs):
    raise FirstRepairBoundary(str(skill), str(kwargs.get("invocation_contract") or ""))


def _forbidden(*_args, **_kwargs):
    raise RuntimeError("Scientific execution, simulation generation and manuscript compilation are prohibited")


def gate_summary(gate: dict) -> dict:
    details = gate.get("details") or {}
    return {"accepted": bool(gate.get("accepted")), "reason": gate.get("reason") or "",
            "issues": list(details.get("issues") or [])}


def diagnosis(host: SnapshotEngine, run, config: dict) -> tuple[dict, dict, object]:
    node = next(node for node in run.nodes if node.id == "paper")
    gate = host._paper_acceptance_gate(
        str(Path(run.project_path)), require_staged=True, require_page_budget=True,
        paper_options=run.options,
    )
    diagnostics = host._gate_revision_diagnostics(gate)
    owner = host._revision_owner_for_gate(node, run, gate)
    return gate, diagnostics, owner


def current_upstream_blockers(root: Path, options: dict) -> list[dict]:
    findings = [*node_risk_audit_service.preflight_node(root, "paper", options),
                *node_risk_audit_service.protected_upstream_findings(root, "paper", options)]
    return [item for item in findings if item.get("severity") == "blocker"
            and str(item.get("upstream_node") or "") not in {"", "paper"}]


def public_blockers(findings: list[dict]) -> list[dict]:
    return [{"id": item.get("id"), "owner_node": item.get("upstream_node"),
             "message": item.get("message"), "target_files": item.get("target_files") or []}
            for item in findings]


def semantic_difference_keys(before: object, after: object, path: str = "") -> list[str]:
    if isinstance(before, dict) and isinstance(after, dict):
        return [key for name in sorted(set(before) | set(after))
                for key in semantic_difference_keys(before.get(name), after.get(name), f"{path}/{name}")]
    if isinstance(before, list) and isinstance(after, list) and len(before) == len(after):
        return [key for index, (left, right) in enumerate(zip(before, after))
                for key in semantic_difference_keys(left, right, f"{path}/{index}")]
    return [path] if before != after else []


async def dispatch(host: SnapshotEngine, run, config: dict, diagnostics: dict, owner) -> dict:
    try:
        output = await host._revise_node_from_gate(
            owner, run, diagnostics, 1, 1, "", str(config.get("direction") or ""),
            str(config.get("effort") or "balanced"), str(config.get("assurance") or "draft"), run.options,
        )
    except FirstRepairBoundary as boundary:
        return {"model_boundary_reached": True, "skill": boundary.skill,
                "write_contract": boundary.contract, "error": ""}
    except (RuntimeError, ValueError) as error:
        return {"model_boundary_reached": False, "error": f"{type(error).__name__}: {error}"}
    return {"model_boundary_reached": False, "runtime_repair_completed": True,
            "runtime_summary": str(output)[:300], "error": ""}


def refresh_narrative_owner(root: Path, run, config: dict, blockers: list[dict], requested: bool) -> tuple[list[dict], dict]:
    result = {"performed": False, "artifact_validation_passed": False}
    if not (requested and blockers and {item.get("upstream_node") for item in blockers} == {"narrative"}):
        return blockers, result
    from server.services.scientific_narrative import scientific_narrative_service

    generated = scientific_narrative_service.ensure(root, str(config.get("direction") or ""),
                                                   preserve_researcher_authored=False)
    report = node_risk_audit_service.audit_node(root, "narrative", run.options, persist=False)
    valid = not any(item.get("severity") == "blocker" for item in report.get("findings") or [])
    result = {"performed": True, "artifact_generated": bool(generated.get("generated")),
              "artifact_validation_passed": valid, "workflow_phase_accepted": False}
    return current_upstream_blockers(root, run.options), result


async def verify(root: Path, run_id: str = "", *, refresh_narrative: bool = False) -> dict:
    host = SnapshotEngine()
    run, config = snapshot_run(root, run_id)
    source_run_id = run.id
    run.id = "paper-repair-snapshot"
    before_paths = [path for directory in (root / "experiments/src", root / "experiments/configs", root / "ideas", root / "literature")
                    for path in directory.rglob("*") if path.is_file()]
    before_paths.extend(path for path in (root / "experiments/results").rglob("*.csv") if path.is_file())
    before_paths.extend(root / relative for relative in (
        "experiments/METHOD_CONTRACT.json", "experiments/RUN_SPEC.json", "experiments/EXPERIMENT_PLAN.md",
        "experiments/results/analysis.md",
    ) if (root / relative).is_file())
    before = hashes(before_paths, root)
    derived_paths = [root / name for name in ("NARRATIVE_REPORT.md", ".merak/NARRATIVE_BUILD.json", "paper/PAPER_PLAN.md")]
    derived_before = hashes([path for path in derived_paths if path.is_file()], root)
    simulation = root / "experiments/results/simulated/SIMULATION_MANIFEST.json"
    simulation_before_value = json.loads(simulation.read_text()) if simulation.is_file() else {}
    simulation_before = simulation_manifest_semantic_hash(simulation_before_value) if simulation.is_file() else ""
    trace_paths = [root / f".merak/runs/{source_run_id}{suffix}" for suffix in (".json", ".skills.json")]
    trace_before = hashes([path for path in trace_paths if path.is_file()], root)
    freeze_before = paper_drafting_service.validate_scientific_freeze(root, run.options)
    print("Repair snapshot: evaluating current paper gates and upstream prerequisites", file=sys.stderr, flush=True)
    initial_gate = None
    with ExitStack() as stack:
        stack.enter_context(patch("server.agent.tools.invoke_skill", _model_boundary))
        stack.enter_context(patch("server.agent.engine.agent_engine.run", _model_boundary))
        stack.enter_context(patch("server.agent.model_transport.ModelTransportMixin._chat_with_progress", _model_boundary))
        stack.enter_context(patch("server.services.simulation_benchmark.build_simulation_benchmark", _forbidden))
        stack.enter_context(patch("server.services.experiment_placeholders.experiment_placeholder_service.ensure", _forbidden))
        stack.enter_context(patch("server.services.paper_compiler.paper_compiler.compile", _forbidden))
        gate, diagnostics, owner = diagnosis(host, run, config)
        initial_gate = copy.deepcopy(gate)
        blockers = current_upstream_blockers(root, run.options)
        initial_blockers = list(blockers)
        blockers, narrative_refresh = refresh_narrative_owner(root, run, config, blockers, refresh_narrative)
        if blockers:
            route = {"model_boundary_reached": False, "upstream_revalidation_required": True,
                     "blocked_owner_ids": sorted({item["upstream_node"] for item in blockers}), "error": ""}
        else:
            print("Repair snapshot: verified upstream inputs; checking runtime refresh and bounded dispatch", file=sys.stderr, flush=True)
            if freeze_before.get("changed_inputs"):
                from server.workflows.paper_repair_runtime import refresh_paper_runtime_inputs

                refreshed = await refresh_paper_runtime_inputs(
                    host, next(node for node in run.nodes if node.id == "paper"), run,
                    str(config.get("direction") or ""), run.options,
                )
                if not refreshed.get("passed"):
                    raise ValueError("Current paper runtime inputs cannot be refreshed: " + "; ".join(refreshed.get("issues") or []))
                gate, diagnostics, owner = diagnosis(host, run, config)
            route = await dispatch(host, run, config, diagnostics, owner)
    scoped = (diagnostics.get("repair_scope") or {}).get("target_files") or []
    unchanged = before == hashes([root / relative for relative in before], root)
    trace_unchanged = trace_before == hashes([root / relative for relative in trace_before], root)
    simulation_unchanged = simulation_before == (
        simulation_manifest_semantic_hash(json.loads(simulation.read_text())) if simulation.is_file() else "")
    scope_legal = "paper/SCIENTIFIC_FREEZE.json" not in scoped
    return {
        "repair_dispatch_verified": bool(owner.id == "paper" and not route.get("error")
                                         and scope_legal and unchanged and trace_unchanged and simulation_unchanged),
        "paper_accepted": bool(gate.get("accepted")), "source_run_id": source_run_id,
        "verification_run_id": run.id, "owner_node": owner.id,
        "gate": gate_summary(gate), "target_files": scoped, "freeze_is_not_model_target": scope_legal,
        "initial_gate": gate_summary(initial_gate),
        "finding_owners": [{"id": item.get("id"), "owner": item.get("owner_node") or item.get("upstream_node"),
                            "category": item.get("category"), "target_files": item.get("target_files") or []}
                           for item in diagnostics.get("findings") or []],
        "dispatch": route, "freeze_changed_inputs_before": freeze_before.get("changed_inputs") or [],
        "upstream_blockers": public_blockers(blockers), "ready_for_paper_model": owner.id == "paper" and not blockers and not route.get("error"),
        "initial_upstream_blockers": public_blockers(initial_blockers), "narrative_producer_refresh": narrative_refresh,
        "derived_prose_changed_files": sorted(relative for relative in derived_before
                                               if hashes([root / relative], root).get(relative) != derived_before[relative]),
        "scientific_inputs_unchanged": unchanged, "copied_source_run_and_trace_unchanged": trace_unchanged,
        "simulation_scientific_semantics_unchanged": simulation_unchanged,
        "simulation_semantic_changed_fields": semantic_difference_keys(
            simulation_manifest_semantic_payload(simulation_before_value),
            simulation_manifest_semantic_payload(json.loads(simulation.read_text()) if simulation.is_file() else {})),
        "model_invoked": False, "scientific_execution_performed": False,
        "manuscript_compiled": False, "live_workflow_resumed": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--run-id", default="")
    parser.add_argument("--keep-snapshot", action="store_true")
    parser.add_argument("--refresh-narrative", action="store_true",
                        help="After an initial safe hold, refresh only the stale narrative in the new copy through its actual producer")
    options = parser.parse_args()
    project = options.project.resolve(strict=True)
    selected = files(project)
    before = hashes(selected, project)
    context = (nullcontext(tempfile.mkdtemp(prefix="paper-repair-snapshot-", dir=REPOSITORY))
               if options.keep_snapshot else tempfile.TemporaryDirectory(prefix="paper-repair-snapshot-", dir=REPOSITORY))
    with context as directory:
        root = Path(directory)
        for source in selected:
            target = root / source.relative_to(project)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        try:
            result = asyncio.run(verify(root, options.run_id, refresh_narrative=options.refresh_narrative))
        except (RuntimeError, ValueError, OSError, KeyError) as error:
            result = {"repair_dispatch_verified": False, "paper_accepted": False,
                      "issues": [f"{type(error).__name__}: {error}"]}
        if options.keep_snapshot:
            result["snapshot_path"] = str(root)
    after = hashes(selected, project)
    result["original_inputs_unchanged"] = before == after
    result["original_changed_files"] = sorted(relative for relative in before if before[relative] != after.get(relative))
    result["repair_dispatch_verified"] = result["repair_dispatch_verified"] and result["original_inputs_unchanged"]
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["repair_dispatch_verified"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
