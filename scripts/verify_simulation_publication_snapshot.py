"""Verify text-only publication projections on an isolated copy of frozen evidence."""

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def verify(project: Path, output: Path) -> dict:
    from server.services.simulation_table_publication_refresh import refresh_simulation_publication_tables
    from server.services.simulation_paper_projection import refresh_simulation_paper_projection
    from server.services.paper_artifacts import simulation_manifest_semantic_hash

    project, output = project.resolve(), output.resolve()
    if not all(path.is_relative_to(ROOT / "output") for path in (project, output)):
        raise ValueError("Snapshot verification requires workspace output paths")
    output.mkdir(parents=True, exist_ok=False)
    original = {}
    for folder in ("paper", "figures", "experiments", "ideas", "literature"):
        for source in (project / folder).rglob("*"):
            if not source.is_file() or "__pycache__" in source.parts:
                continue
            if source.is_symlink() or not source.resolve().is_relative_to(project):
                raise ValueError("Snapshot refuses external links")
            target = output / source.relative_to(project)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            original[source] = hashlib.sha256(source.read_bytes()).hexdigest()
    manifest = output / "experiments/results/simulated/SIMULATION_MANIFEST.json"
    before = json.loads(manifest.read_bytes())
    identity = simulation_manifest_semantic_hash(before)
    tables = refresh_simulation_publication_tables(output)
    figures = refresh_simulation_paper_projection(output)
    second = (refresh_simulation_publication_tables(output), refresh_simulation_paper_projection(output))
    after = json.loads(manifest.read_bytes())
    unchanged = all(hashlib.sha256((output / item["path"]).read_bytes()).hexdigest() == item["sha256"]
                    for item in before["data_files"])
    source_unchanged = all(hashlib.sha256(path.read_bytes()).hexdigest() == digest for path, digest in original.items())
    result = {"accepted": unchanged and source_unchanged and identity == simulation_manifest_semantic_hash(after)
                         and second == (False, False),
        "tables_changed": tables, "figures_changed": figures, "second_pass_changed": second,
        "data_unchanged": unchanged, "source_project_unchanged": source_unchanged,
        "scientific_identity_unchanged": identity == simulation_manifest_semantic_hash(after),
        "training_executed": False, "model_invoked": False}
    (output / "verification.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = verify(args.project, args.output)
    print(json.dumps(result))
    raise SystemExit(0 if result["accepted"] else 1)
