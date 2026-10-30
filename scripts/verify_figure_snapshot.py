"""Render and validate deterministic figures in an isolated source snapshot.

This tool never resumes a workflow, invokes a model, executes experiment source,
or generates simulation data. Existing preview data/variants retain their
synthetic status. Only deterministic figure code renders local SVG/PDF/PNG files
inside a new temporary workspace; original project hashes are checked afterward.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import shutil
import sys
import tempfile
from contextlib import ExitStack, nullcontext
from pathlib import Path
from unittest.mock import patch


REPOSITORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY))

from server.services.deterministic_figure_builder import _current_entry_reusable, ensure_evaluation_design
from server.services.figure_artifacts import figure_artifact_registry as registry
from server.services.figure_engine import figure_engine
from server.services.figure_spec_repository import persist_figure_specs
from server.services.scientific_assets import scientific_asset_service
from server.services.simulation_figure_refresh import refresh_existing_simulation_figures
from server.workflows.engine import WorkflowEngine
from server.workflows.models import WorkflowRun
from server.workflows.revision_loop_context import RevisionComplete, RevisionLoopContext
from server.workflows.revision_loop_phases import initialize_revision, initialize_progress
from server.workflows.revision_gate_phases import (
    persist_gate_inputs, build_current_gate, record_runtime_gate,
    verify_runtime_execution, normalize_gate_outcome, complete_accepted_gate,
)
from server.workflows.run_execution_context import RunExecutionContext
from server.workflows.run_execution_execute import persist_node_acceptance, refresh_node_audits
from server.workflows.run_state import RunState
from scripts.snapshot_execution_trace import clone_execution_envelope, archived_execution_source_unchanged


def files(project: Path) -> list[Path]:
    allowed = {
        "ideas": {".json", ".md"}, "experiments/src": {".py"},
        "experiments/configs": {".yaml", ".yml", ".json"},
        "experiments/results/simulated": {".csv", ".json", ".jsonl", ".md", ".py", ".yaml", ".yml"},
        "experiments/results/templates": {".csv", ".json", ".md"},
        "literature": {".md", ".json", ".bib"}, "paper/tables": {".csv", ".tex", ".json"},
        "figures": {".json", ".md", ".py", ".svg", ".pdf", ".png"},
    }
    selected = [project / name for name in (
        "experiments/METHOD_CONTRACT.json", "experiments/RUN_SPEC.json", "experiments/EXPERIMENT_PLAN.md",
        "experiments/IMPLEMENTATION_BLUEPRINT.json", "experiments/IMPLEMENTATION_BUILD.json",
        "experiments/IMPLEMENTATION_EVIDENCE_PATCH.json", "paper/PUBLICATION_STYLE.json", "paper/PAPER_PLAN.md",
        "paper/synthetic_preview_figures.tex", "NARRATIVE_REPORT.md", "MANIFEST.md",
        "experiments/results/analysis.md", ".merak/NARRATIVE_BUILD.json",
        ".merak/research_strategy.json", ".merak/PAPER_PLAN_BUILD.json",
    )]
    runs = project / ".merak/runs"
    selected.extend(path for path in runs.glob("*.json")
                    if path.name.endswith((".skills.json", ".specialists.json"))
                    or path.stem.isalnum())
    for directory, suffixes in allowed.items():
        selected.extend(path for path in (project / directory).rglob("*") if path.suffix in suffixes)
    result = sorted({path for path in selected if path.is_file()})
    for path in result:
        if not path.resolve().is_relative_to(project) or path.stat().st_size > 20 * 1024 * 1024:
            raise ValueError(f"Figure snapshot target escapes project or exceeds bound: {path}")
    return result


def hashes(paths: list[Path], root: Path) -> dict[str, str]:
    return {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}


def entries(root: Path) -> dict[str, dict]:
    return {str((item.get("metadata") or {}).get("semantic_key") or item.get("id")): item
            for item in registry.load(root / "figures").get("figures") or []}


class SnapshotEngine(WorkflowEngine):
    """Capture actual node events without opening services or a WebSocket."""

    def __init__(self):
        super().__init__()
        self.snapshot_events = []

    async def _emit(self, _run, event, data):
        self.snapshot_events.append((event, data))


def snapshot_run(root: Path, run_id: str = "") -> tuple[WorkflowRun, dict]:
    paths = ([root / f".merak/runs/{run_id}.json"] if run_id else
             sorted((root / ".merak/runs").glob("*.json"), key=lambda path: path.stat().st_mtime, reverse=True))
    for path in paths:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(payload, dict) or not payload.get("phases") or not payload.get("run_id"):
            continue
        options = dict((payload.get("config") or {}).get("options") or {})
        if options.get("run_experiment") is True:
            raise ValueError("Scientific execution-enabled runs are not supported by this snapshot verifier")
        nodes = SnapshotEngine()._get_default_nodes()
        run = WorkflowRun(id=payload["run_id"], project_path=str(root), options=options,
                          input_baseline=dict(payload.get("input_baseline") or {}), nodes=nodes)
        return run, dict(payload.get("config") or {})
    raise ValueError("Snapshot verification requires a persisted workflow run and its actual skill trace")


async def verify_full_node(root: Path, direction: str, run_id: str = "") -> dict:
    """Exercise the real acceptance and execution phases without running a workflow."""
    host = SnapshotEngine()
    run, config = snapshot_run(root, run_id)
    node = next(node for node in run.nodes if node.id == "figure")
    direction = direction or str(config.get("direction") or "")
    assurance = str(config.get("assurance") or "draft")
    print("Snapshot: checking the complete figure node and copied upstream execution trace", file=sys.stderr, flush=True)
    before_sources = hashes([path for path in (root / "experiments/src").rglob("*") if path.is_file()], root)
    before_data = hashes([path for path in (root / "experiments/results/simulated").rglob("*.csv")], root)
    before_trace = json.loads((root / f".merak/runs/{run.id}.skills.json").read_text(encoding="utf-8-sig"))
    prior_ids = [node.id for node in run.nodes[:run.nodes.index(node)]]
    prior_trace = {identity: before_trace.get("stages", {}).get(identity) for identity in prior_ids}
    operation, service = await host._runtime_execution_started(node, run, run.options)
    print("Snapshot: preparing canonical artifacts with the actual node adapter", file=sys.stderr, flush=True)
    result = await host._prepare_node_for_gate(
        node, run, "Source snapshot deterministic figure validation", direction, assurance, run.options,
    )
    await host._runtime_execution_finished(node, run, operation, service, output=result)
    ctx = RevisionLoopContext(host, node, run, assurance, direction,
                              str(config.get("effort") or "balanced"), run.options,
                              1, 1, result, False, 2)
    await initialize_revision(ctx)
    await initialize_progress(ctx)
    await persist_gate_inputs(ctx)
    ctx.preparation_error = ""
    await build_current_gate(ctx)
    print("Snapshot: verifying runtime and every prior node execution owner", file=sys.stderr, flush=True)
    artifact_gate_accepted = bool(host._figure_acceptance_gate(str(root))["accepted"])
    await record_runtime_gate(ctx)
    await verify_runtime_execution(ctx)
    await normalize_gate_outcome(ctx)
    if ctx.gate.get("accepted"):
        print("Snapshot: persisting the accepted node outcome", file=sys.stderr, flush=True)
        try:
            await complete_accepted_gate(ctx)
        except RevisionComplete:
            pass
        outcome = RunExecutionContext(host, run, direction, "balanced", assurance, run.options,
                                      run_state=ctx.run_state, node=node, gate=ctx.gate, result=result)
        await persist_node_acceptance(outcome)
        await refresh_node_audits(outcome)
    phase = (RunState(str(root), run.id).load() or {}).get("phases", {}).get("figure", {})
    details = ctx.gate.get("details") or {}
    after_trace = json.loads((root / f".merak/runs/{run.id}.skills.json").read_text(encoding="utf-8-sig"))
    preserved = (
        before_sources == hashes([root / value for value in before_sources], root)
        and before_data == hashes([root / value for value in before_data], root)
        and prior_trace == {identity: after_trace.get("stages", {}).get(identity) for identity in prior_ids}
    )
    return {"accepted": bool(ctx.gate.get("accepted")), "artifact_gate_accepted": artifact_gate_accepted,
            "issues": details.get("issues") or ([ctx.gate.get("summary")] if not ctx.gate.get("accepted") else []),
            "execution_evidence": details.get("execution_evidence") or {},
            "workflow_execution_evidence": details.get("workflow_execution_evidence") or {},
            "persisted_figure_status": phase.get("status"), "run_id": run.id,
            "source_and_numeric_data_unchanged": preserved,
            "upstream_execution_trace_unchanged": prior_trace == {
                identity: after_trace.get("stages", {}).get(identity) for identity in prior_ids}}


async def verify(root: Path, direction: str, run_id: str = "", *, original_project: Path | None = None) -> dict:
    # Reproject the already hashed numeric rows; never call the simulator.
    refreshed_previews = await refresh_existing_simulation_figures(root)
    original_plan = scientific_asset_service.load(root)
    old_specs = json.loads((root / "figures/FIGURE_SPECS.json").read_text(encoding="utf-8-sig"))
    style = original_plan.get("publication_style_contract") or {}
    plan = scientific_asset_service.build_plan(
        root, experiment_requested=False, requested_evidence_mode=original_plan["evidence_mode"],
        direction=direction, target_venue=str(style.get("target_venue") or "ICLR"),
    )
    if plan["evidence_mode"] != original_plan["evidence_mode"]:
        raise ValueError("Snapshot changed the scientific evidence mode")
    specs = persist_figure_specs(root, plan)
    active_ids = {item["id"] for item in specs}
    prior_preview_ids = {item["id"] for item in old_specs["figures"] if item.get("evidence_status") == "synthetic_preview"}
    if not prior_preview_ids <= active_ids:
        raise ValueError("Required synthetic preview assets disappeared")
    historical = next((item for item in old_specs["figures"] if item.get("id") == "core_mechanism"), None)
    render_specs = specs + ([historical] if historical and "core_mechanism" not in active_ids else [])
    events = []

    class Host:
        async def _emit(self, _run, event, data):
            events.append((event, data.get("asset_id")))

    def forbidden(*_args, **_kwargs):
        raise RuntimeError("Model, simulation, or scientific execution is prohibited in figure snapshot verification")

    run = WorkflowRun(id="figure-snapshot", project_path=str(root), options={"run_experiment": False})
    with ExitStack() as stack:
        stack.enter_context(patch("server.agent.engine.agent_engine.run", forbidden))
        stack.enter_context(patch("server.agent.model_transport.ModelTransportMixin._chat_with_progress", forbidden))
        stack.enter_context(patch("server.services.simulation_benchmark.build_simulation_benchmark", forbidden))
        stack.enter_context(patch("server.agent.tools.invoke_skill", forbidden))
        await ensure_evaluation_design(Host(), run, root / "figures", render_specs, plan, set(), registry)
        generated = [identity for event, identity in events if event == "figure_deterministic_asset_generated"]
        events.clear()
        await ensure_evaluation_design(Host(), run, root / "figures", render_specs, plan, set(), registry)
    stable_reuse = not events
    before = entries(root)
    method = before["method_architecture"]
    png = root / method["metadata"]["rendered_variants"]["png"]
    original_png = png.read_bytes()
    png.write_bytes(original_png + b"tamper-test")
    tamper_rejected = not _current_entry_reusable(method, root, method["metadata"]["producer_input_sha256"])
    png.write_bytes(original_png)
    selected_run, _config = snapshot_run(root, run_id)
    if original_project is None:
        raise ValueError("Full figure snapshot requires its read-only original project for explicit execution-envelope cloning")
    relocation = clone_execution_envelope(root, original_project, selected_run.id)
    with ExitStack() as stack:
        stack.enter_context(patch("server.agent.engine.agent_engine.run", forbidden))
        stack.enter_context(patch("server.agent.model_transport.ModelTransportMixin._chat_with_progress", forbidden))
        stack.enter_context(patch("server.services.simulation_benchmark.build_simulation_benchmark", forbidden))
        stack.enter_context(patch("server.services.experiment_placeholders.experiment_placeholder_service.ensure", forbidden))
        stack.enter_context(patch("server.agent.tools.invoke_skill", forbidden))
        gate = await verify_full_node(root, direction, run_id)
    return {
        "accepted": bool(gate["accepted"]) and stable_reuse and tamper_rejected
        and gate["source_and_numeric_data_unchanged"] and gate["persisted_figure_status"] == "accepted"
        and archived_execution_source_unchanged(root, relocation),
        "issues": gate.get("issues", []), "generated_assets": generated,
        "full_node_acceptance": gate,
        "required_assets": sorted(item["id"] for item in specs if item.get("required")),
        "second_pass_reused": stable_reuse, "tampered_variant_rejected": tamper_rejected,
        "evidence_mode": plan["evidence_mode"], "scientific_execution_performed": False,
        "refreshed_preview_assets": refreshed_previews,
        "execution_snapshot_clone": relocation,
        "archived_source_execution_trace_unchanged": archived_execution_source_unchanged(root, relocation),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--direction", default="")
    parser.add_argument("--run-id", default="", help="Use this existing run and its copied execution trace")
    parser.add_argument("--keep-snapshot", action="store_true", help="Retain the new isolated workspace for visual inspection")
    options = parser.parse_args()
    project = options.project.resolve(strict=True)
    selected = files(project)
    before = hashes(selected, project)
    temporary_context = (nullcontext(tempfile.mkdtemp(prefix="figure-snapshot-", dir=REPOSITORY))
                         if options.keep_snapshot else tempfile.TemporaryDirectory(prefix="figure-snapshot-", dir=REPOSITORY))
    with temporary_context as temporary:
        root = Path(temporary)
        for source in selected:
            target = root / source.relative_to(project)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        try:
            result = asyncio.run(verify(root, options.direction, options.run_id, original_project=project))
        except (RuntimeError, ValueError, OSError) as error:
            result = {"accepted": False, "issues": [str(error)]}
        if options.keep_snapshot:
            result["snapshot_path"] = str(root)
    result["original_inputs_unchanged"] = before == hashes(selected, project)
    result["accepted"] = result["accepted"] and result["original_inputs_unchanged"]
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["accepted"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
