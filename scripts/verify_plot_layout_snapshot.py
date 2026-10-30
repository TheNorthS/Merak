"""Explicit render-only validation on a new snapshot of authenticated plot artifacts."""

import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import shutil
import sys

REPOSITORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY))


async def verify(project: Path, output: Path) -> dict:
    from server.services.simulation_artifact_io import render_simulation_script
    from server.services.simulation_figure_refresh import _MANIFEST
    from server.services.simulation_plot_layout_refresh import refresh_cropped_plot_labels
    from server.services.figure_artifacts import figure_artifact_registry
    from server.services.paper_artifacts import simulation_manifest_semantic_hash

    project, output = project.resolve(), output.resolve()
    if not project.is_relative_to(REPOSITORY / "output") or not output.is_relative_to(REPOSITORY / "output"):
        raise ValueError("Render validation must remain under workspace output")
    output.mkdir(parents=True, exist_ok=False)
    manifest = json.loads((project / _MANIFEST).read_bytes())
    paths = {_MANIFEST, "figures/FIGURE_MANIFEST.json", "figures/FIGURE_MANIFEST.md",
             "experiments/results/templates/PLANNED_RESULT_MANIFEST.json", "paper/PUBLICATION_STYLE.json"}
    paths.update(item["path"] for item in manifest["data_files"])
    for item in manifest["figure_files"]:
        paths.update((item["source"], *item["outputs"].values()))
    for relative in paths:
        source = (project / relative).resolve()
        if not source.is_relative_to(project):
            raise ValueError("Snapshot source escapes project")
        if source.is_file():
            target = output / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
    changed = await refresh_cropped_plot_labels(output, render_simulation_script)
    after = json.loads((output / _MANIFEST).read_bytes())
    data_unchanged = all(hashlib.sha256((output / item["path"]).read_bytes()).hexdigest() == item["sha256"]
                         for item in manifest["data_files"])
    issues = {item["id"]: figure_artifact_registry.raster_layout_issues(output / item["outputs"]["png"])
              for item in after["figure_files"]}
    second = await refresh_cropped_plot_labels(output, render_simulation_script)
    result = {"changed": changed, "data_unchanged": data_unchanged, "issues": issues,
              "scientific_identity_unchanged": simulation_manifest_semantic_hash(manifest) == simulation_manifest_semantic_hash(after),
              "second_pass_changes": second, "training_executed": False, "project_modified": False}
    result["accepted"] = data_unchanged and result["scientific_identity_unchanged"] and not second and not any(issues.values())
    (output / "verification.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    result = asyncio.run(verify(arguments.project, arguments.output))
    print(json.dumps(result))
    raise SystemExit(0 if result["accepted"] else 1)
