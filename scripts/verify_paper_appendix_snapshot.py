"""Compile an isolated appendix projection; never certify the manuscript's science."""

import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


async def verify(project: Path, output: Path) -> dict:
    from scripts.verify_simulation_publication_snapshot import verify as copy_verify
    from server.services.paper_drafting import paper_drafting_service
    from server.services.paper_compiler import paper_compiler
    from server.services.paper_print_repair import compile_print_verified_paper
    from server.services.paper_appendix_assembly import original_assembly_inputs

    copied = copy_verify(project, output)
    if not copied["accepted"]:
        raise ValueError("Source snapshot did not preserve frozen evidence")
    output = output.resolve()
    sections = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in (output / "paper/sections").glob("*.tex")}
    paper_drafting_service.assemble(output)
    result = await compile_print_verified_paper(paper_compiler, output)
    preserved = all(hashlib.sha256(path.read_bytes()).hexdigest() == value for path, value in sections.items())
    validated = original_assembly_inputs(output) if result.success else set()
    receipt = {"accepted": result.success and preserved and bool(validated), "scientific_acceptance": False,
        "compile_success": result.success, "pdf_path": str(result.pdf_path or ""),
        "author_sections_unchanged": preserved, "original_sections_validated": sorted(validated),
        "compile_errors": [str(error) for error in result.errors],
        "model_invoked": False, "training_executed": False, "source_project_unchanged": copied["source_project_unchanged"]}
    (output / "appendix-verification.json").write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    return receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = asyncio.run(verify(args.project, args.output))
    print(json.dumps(result))
    raise SystemExit(0 if result["accepted"] else 1)
