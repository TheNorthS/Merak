"""Verify real paper preparation in a copy, stopping before the first model call.

No workflow resumes, manuscript compilation, model invocation or simulation
generation are permitted. Success means ready for bounded authoring only; it is
not paper acceptance and does not change the original project's workflow state.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import shutil
import sys
import tempfile
from contextlib import ExitStack, nullcontext
from pathlib import Path
from unittest.mock import patch


REPOSITORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY))

from scripts.verify_figure_snapshot import files as figure_files, hashes, snapshot_run, SnapshotEngine
from server.services.paper_artifacts import bind_table_manifest_hashes
from server.services.paper_drafting import paper_drafting_service


class FirstAuthoringBoundary(BaseException):
    """A successful preparation reaches this sentinel instead of a model provider."""

    def __init__(self, skill: str, arguments: str, contract: str):
        self.skill = skill
        self.arguments = arguments
        self.contract = contract


def files(project: Path) -> list[Path]:
    selected = figure_files(project)
    extensions = {".tex", ".md", ".json", ".csv", ".bib", ".txt", ".cls", ".sty", ".bst"}
    selected.extend(path for path in (project / "paper").rglob("*")
                    if path.is_file() and path.suffix.casefold() in extensions)
    selected.extend(path for path in (project / ".merak").glob("*.json") if path.is_file())
    unique = sorted(set(selected))
    for path in unique:
        if not path.resolve().is_relative_to(project) or path.stat().st_size > 20 * 1024 * 1024:
            raise ValueError("Paper snapshot input escapes its project or exceeds the local fixture bound")
    return unique


def _forbidden(*_args, **_kwargs):
    raise RuntimeError("Model, scientific execution, simulation generation and manuscript compilation are prohibited")


def _boundary(skill, arguments, **kwargs):
    raise FirstAuthoringBoundary(str(skill), str(arguments), str(kwargs.get("invocation_contract") or ""))


def _table_contract(root: Path) -> dict:
    path = root / "paper/tables/TABLE_MANIFEST.json"
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    _bound, issues, _ = bind_table_manifest_hashes(root, payload)
    projections = [item.get("publication_projection") or {} for item in payload.get("tables") or []]
    notes = [note for projection in projections for note in projection.get("notes") or []]
    return {"accepted": not issues, "issues": issues, "table_count": len(payload.get("tables") or []),
            "source_bound_full_text_notes": len(notes)}


async def verify(root: Path, run_id: str = "") -> dict:
    host = SnapshotEngine()
    run, config = snapshot_run(root, run_id)
    source_run_id = run.id
    # Preparation does not consume upstream execution attestations. Its local
    # invocation gets a separate identity; copied real traces stay untouched.
    run.id = "paper-preparation-snapshot"
    node = next(node for node in run.nodes if node.id == "paper")
    direction = str(config.get("direction") or "")
    source_paths = [path for path in (root / "experiments/src").rglob("*") if path.is_file()]
    numeric_paths = [path for path in (root / "experiments/results").rglob("*.csv") if path.is_file()]
    before = hashes([*source_paths, *numeric_paths, root / "ideas/SELECTED_IDEA.json",
                     root / "experiments/METHOD_CONTRACT.json", root / "experiments/RUN_SPEC.json"], root)
    copied_run_paths = [root / f".merak/runs/{source_run_id}{suffix}" for suffix in (".json", ".skills.json")]
    copied_run_before = hashes([path for path in copied_run_paths if path.is_file()], root)
    figure_before = hashes([path for path in (root / "figures").rglob("*") if path.is_file()
                            and path.name not in {"FIGURE_MANIFEST.json", "FIGURE_MANIFEST.md"}], root)
    figure_manifest_before = hashes([path for path in (root / "figures").glob("FIGURE_MANIFEST.*") if path.is_file()], root)
    reached = None
    with ExitStack() as stack:
        stack.enter_context(patch("server.agent.tools.invoke_skill", _boundary))
        stack.enter_context(patch("server.agent.engine.agent_engine.run", _forbidden))
        stack.enter_context(patch("server.agent.model_transport.ModelTransportMixin._chat_with_progress", _forbidden))
        stack.enter_context(patch("server.services.simulation_benchmark.build_simulation_benchmark", _forbidden))
        stack.enter_context(patch("server.services.experiment_placeholders.experiment_placeholder_service.ensure", _forbidden))
        stack.enter_context(patch("server.services.paper_compiler.paper_compiler.compile", _forbidden))
        try:
            await host._execute_staged_paper(
                node=node, run=run, research_direction=direction, opts=run.options,
            )
        except FirstAuthoringBoundary as boundary:
            reached = boundary
    if reached is None:
        raise ValueError("Paper preparation did not reach a first authoring boundary")
    tables = _table_contract(root)
    freeze = paper_drafting_service.validate_scientific_freeze(root, run.options)
    paths = paper_drafting_service.paths(root)
    state = json.loads(paths["state"].read_text(encoding="utf8"))
    contracts = json.loads(paths["contracts"].read_text(encoding="utf8"))
    unchanged = before == hashes([root / relative for relative in before], root)
    original_trace_unchanged = copied_run_before == hashes([root / relative for relative in copied_run_before], root)
    figure_gate = host._figure_acceptance_gate(str(root))
    figures_unchanged = figure_before == hashes([root / relative for relative in figure_before], root)
    stage = re.search(r"^Stage:\s*([a-z_]+)\s*$", reached.arguments, re.MULTILINE)
    return {
        "ready_for_authoring": bool(tables["accepted"] and freeze.get("passed") and unchanged
                                    and original_trace_unchanged and figures_unchanged and reached.contract.strip() and stage),
        "paper_accepted": False, "first_model_boundary_reached": True,
        "first_skill": reached.skill, "first_stage": stage.group(1) if stage else "",
        "invocation_contract_present": bool(reached.contract.strip()),
        "section_contract_count": len(contracts.get("sections") or []),
        "scientific_freeze_passed": bool(freeze.get("passed")),
        "tables": tables, "issues": list(tables["issues"]) + list(freeze.get("issues") or []),
        "evidence_mode": (state.get("evidence") or {}).get("mode"),
        "source_contracts_and_numeric_data_unchanged": unchanged,
        "copied_source_run_and_trace_unchanged": original_trace_unchanged,
        "figure_artifact_gate_accepted": bool(figure_gate.get("accepted")),
        "figure_assets_unchanged": figures_unchanged,
        "figure_manifest_reconciled": figure_manifest_before != hashes(
            [root / relative for relative in figure_manifest_before], root),
        "model_invoked": False, "scientific_execution_performed": False,
        "manuscript_compiled": False, "live_workflow_resumed": False,
        "source_run_id": source_run_id, "verification_run_id": run.id,
        "preparation_trace_scope": "isolated pre-model invocation; copied original execution trace was not rebound",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--run-id", default="")
    parser.add_argument("--keep-snapshot", action="store_true")
    options = parser.parse_args()
    project = options.project.resolve(strict=True)
    selected = files(project)
    before = hashes(selected, project)
    context = (nullcontext(tempfile.mkdtemp(prefix="paper-preparation-snapshot-", dir=REPOSITORY))
               if options.keep_snapshot else tempfile.TemporaryDirectory(prefix="paper-preparation-snapshot-", dir=REPOSITORY))
    with context as directory:
        root = Path(directory)
        for source in selected:
            target = root / source.relative_to(project)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        try:
            result = asyncio.run(verify(root, options.run_id))
        except (RuntimeError, ValueError, OSError, KeyError) as error:
            result = {"ready_for_authoring": False, "paper_accepted": False,
                      "issues": [f"{type(error).__name__}: {error}"]}
        if options.keep_snapshot:
            result["snapshot_path"] = str(root)
    result["original_inputs_unchanged"] = before == hashes(selected, project)
    result["ready_for_authoring"] = result["ready_for_authoring"] and result["original_inputs_unchanged"]
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["ready_for_authoring"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
