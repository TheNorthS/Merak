"""Render only an existing method architecture in a new, source-bound copy.

No scientific owner contract is rewritten. Nodes and relations must equal the
authored projection; SVG/PDF/PNG pass actual producer and registry validation.
The original project remains read-only and no model or workflow may execute.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import sys
import tempfile
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

REPOSITORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY))

from scripts.verify_figure_snapshot import SnapshotEngine, hashes
from server.services.deterministic_figure_builder import ensure_evaluation_design
from server.services.figure_artifacts import figure_artifact_registry as registry
from server.services.figure_semantic_projection import project_figure_semantics
from server.workflows.models import WorkflowRun


def _forbidden(*_args, **_kwargs):
    raise RuntimeError("Model, workflow, simulation and scientific execution are prohibited")


async def verify(root: Path, asset: dict, plan: dict) -> dict:
    host = SnapshotEngine()
    run = WorkflowRun(id="method-architecture-snapshot", project_path=str(root), options={"run_experiment": False})
    with ExitStack() as stack:
        for target in ("server.agent.tools.invoke_skill", "server.agent.engine.agent_engine.run",
                       "server.agent.model_transport.ModelTransportMixin._chat_with_progress",
                       "server.services.simulation_benchmark.build_simulation_benchmark"):
            stack.enter_context(patch(target, _forbidden))
        await ensure_evaluation_design(host, run, root / "figures", [asset], plan, {"method_architecture"}, registry)
    valid, issues, payload = registry.validate(root / "figures")
    issues += registry.scientific_quality_issues(root / "figures")
    issues += registry.scientific_alignment_issues(root / "figures")
    entry = next(item for item in payload["figures"] if item["id"] == "method_architecture")
    source = json.loads((root / entry["source_path"]).read_text(encoding="utf8"))
    projected = project_figure_semantics(asset)
    expected_nodes = {item["id"] for item in projected["entities_states_transformations"]}
    expected_relations = {(item["from"], item["to"], item["kind"]) for item in projected["relations"]}
    actual_relations = {(item["from"], item["to"], item["scientific_kind"]) for item in source["edges"]}
    faithful = expected_nodes == {item["id"] for item in source["nodes"]} and expected_relations == actual_relations
    review = entry["metadata"]["visual_review_rounds"][-1]
    return {"accepted": bool(valid and not issues and faithful), "issues": issues,
            "rendered_node_count": len(source["nodes"]), "rendered_relation_count": len(source["edges"]),
            "projection_excluded_ids": sorted(projected["excluded"]), "authored_projection_preserved": faithful,
            "rendered_variants": sorted(entry["metadata"]["rendered_variants"]),
            "local_visual_review_passed": review["status"] == "passed",
            "model_invoked": False, "scientific_execution_performed": False, "workflow_resumed": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    options = parser.parse_args()
    project = options.project.resolve(strict=True)
    spec_path = project / "figures/FIGURE_SPECS.json"
    plan_path = project / "figures/SCIENTIFIC_ASSET_PLAN.json"
    specs = json.loads(spec_path.read_text(encoding="utf-8-sig"))
    plan = json.loads(plan_path.read_text(encoding="utf-8-sig"))
    asset = next(item for item in specs["figures"] if item["id"] == "method_architecture")
    paths = {spec_path, plan_path}
    paths.update((project / value).resolve() for value in asset["source_data"])
    for path in paths:
        if not path.is_relative_to(project) or not path.is_file():
            raise ValueError("Method snapshot source is missing or leaves the original project")
    before = hashes(sorted(paths), project)
    with tempfile.TemporaryDirectory(prefix="method-architecture-snapshot-", dir=REPOSITORY) as directory:
        root = Path(directory)
        for source in paths:
            target = root / source.relative_to(project)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        try:
            result = asyncio.run(verify(root, asset, plan))
        except (RuntimeError, ValueError, OSError, KeyError) as error:
            result = {"accepted": False, "issues": [f"{type(error).__name__}: {error}"]}
        copied_inputs = hashes([root / relative for relative in before], root)
        result["copied_scientific_inputs_unchanged"] = all(before[relative] == copied_inputs[relative]
                                                           for relative in before if not relative.startswith("figures/"))
    result["original_inputs_unchanged"] = before == hashes(sorted(paths), project)
    result["accepted"] = result["accepted"] and result["original_inputs_unchanged"] and result["copied_scientific_inputs_unchanged"]
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["accepted"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
