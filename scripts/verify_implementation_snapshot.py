"""Revalidate a read-only project snapshot without models or scientific execution.

Only declared design/source contracts are copied into a temporary workspace.
The original project is fingerprinted before and after; generated source is
parsed by validators, never imported, trained, or invoked.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import shutil
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch


REPOSITORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY))

from server.services.experiment_implementation_build import experiment_implementation_build_service as service
from server.workflows.models import WorkflowNode, WorkflowRun
from server.workflows.staged_implementation_coordinator import StagedImplementationCoordinator


CONTRACT_PATHS = (
    "ideas/SELECTED_IDEA.json", "experiments/EXPERIMENT_PLAN.md",
    "experiments/METHOD_CONTRACT.json", "experiments/RUN_SPEC.json",
    "experiments/IMPLEMENTATION_BLUEPRINT.json", "experiments/IMPLEMENTATION_BUILD.json",
    "experiments/IMPLEMENTATION_EVIDENCE_PATCH.json", "paper/PUBLICATION_STYLE.json",
    ".merak/RESEARCH_WORKFLOW_CONTRACT.json",
)


def snapshot_files(project: Path) -> list[Path]:
    paths = [project / relative for relative in CONTRACT_PATHS]
    for relative, suffixes in (
        ("experiments/src", {".py"}),
        ("experiments/configs", {".yaml", ".yml", ".json", ".toml", ".ini", ".cfg"}),
    ):
        directory = project / relative
        if directory.is_dir():
            paths.extend(path for path in directory.rglob("*") if path.suffix in suffixes)
    files = sorted({path for path in paths if path.is_file()})
    for path in files:
        if not path.resolve().is_relative_to(project) or path.stat().st_size > 5 * 1024 * 1024:
            raise ValueError(f"Snapshot target escapes project or exceeds the source-only limit: {path}")
    return files


def hashes(paths: list[Path], root: Path) -> dict[str, str]:
    return {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}


async def verify_copy(root: Path, direction: str) -> dict:
    model_calls = 0

    async def forbid_model(_self):
        nonlocal model_calls
        model_calls += 1
        raise RuntimeError("Static snapshot still requires a model-owned repair; no model was invoked")

    class Host:
        async def _emit(self, _run, _event, _data):
            return None

    run = WorkflowRun(id="static-snapshot", project_path=str(root), status="running", nodes=[
        WorkflowNode("exp-design", "Design", "/experiment-plan"),
    ])
    owner_sources = sorted((root / "experiments/src").glob("*.py"))
    source_hashes = hashes(owner_sources, root)
    with patch("server.workflows.implementation_model_invocation.StageModelInvocation.run", forbid_model):
        try:
            report = await StagedImplementationCoordinator(Host(), run, direction).execute()
        except RuntimeError as error:
            return {"complete": False, "model_calls": model_calls, "issues": [str(error)]}
        before = hashes([service.build_path(root), root / "experiments/METHOD_CONTRACT.json"], root)
        second = await StagedImplementationCoordinator(Host(), run, direction).execute()
    unchanged = source_hashes == hashes(owner_sources, root)
    reusable = all(service.can_reuse(root, stage.id, direction) for stage in service.stages(root, direction))
    stable = before == hashes([service.build_path(root), root / "experiments/METHOD_CONTRACT.json"], root)
    return {
        "complete": not report["blocking"] and not second["blocking"] and unchanged and reusable and stable,
        "model_calls": model_calls, "issues": report["issues"],
        "owner_sources_unchanged": unchanged, "all_stages_reusable": reusable,
        "second_pass_stable": stable,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--direction", default="")
    options = parser.parse_args()
    project = options.project.resolve(strict=True)
    files = snapshot_files(project)
    before = hashes(files, project)
    with tempfile.TemporaryDirectory(prefix="implementation-snapshot-", dir=REPOSITORY) as folder:
        root = Path(folder)
        for path in files:
            target = root / path.relative_to(project)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
        result = asyncio.run(verify_copy(root, options.direction))
    after = hashes(files, project)
    result["changed_original_inputs"] = [name for name, digest in before.items() if after.get(name) != digest]
    result["original_inputs_unchanged"] = not result["changed_original_inputs"]
    result["scientific_execution_performed"] = False
    result["complete"] = result["complete"] and result["original_inputs_unchanged"]
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["complete"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
