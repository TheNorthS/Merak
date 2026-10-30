"""Run the authorized paper print producer on a separate snapshot without model calls."""

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
    from server.services.paper_print_repair import prepare_print_figures

    project, output = project.resolve(), output.resolve()
    if not all(path.is_relative_to(REPOSITORY / "output") for path in (project, output)):
        raise ValueError("Print verification must remain under output")
    output.mkdir(parents=True, exist_ok=False)
    for folder in ("paper", "figures", "experiments", "ideas", "literature"):
        for source in (project / folder).rglob("*"):
            if not source.is_file() or "__pycache__" in source.parts:
                continue
            if source.is_symlink() or not source.resolve().is_relative_to(project):
                raise ValueError("Print snapshot refuses external links")
            target = output / source.relative_to(project)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
    originals = {path: hashlib.sha256(path.read_bytes()).hexdigest() for folder in ("figures", "experiments")
                 for path in (output / folder).rglob("*") if path.is_file()}
    try:
        packets = await prepare_print_figures(output)
        result = {"accepted": True, "assets": [packet.get("asset_id") for packet in packets]}
    except ValueError as error:
        result = {"accepted": False, "error": str(error)}
    result["originals_unchanged"] = all(hashlib.sha256(path.read_bytes()).hexdigest() == digest
                                        for path, digest in originals.items())
    result.update(training_executed=False, model_invoked=False, original_project_modified=False)
    (output / "verification.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = asyncio.run(verify(args.project, args.output))
    print(json.dumps(result))
    raise SystemExit(0 if result["accepted"] and result["originals_unchanged"] else 1)
