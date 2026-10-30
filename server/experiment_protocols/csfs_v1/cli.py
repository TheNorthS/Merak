"""Explicit CSFS-v1 source check or researcher-authorized scientific execution."""

from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path

import yaml

from .execution_io import source_inventory
from .protocol import PROTOCOL_ID, ProtocolError, require_registered_config


def source_check(root: Path, config: dict) -> dict:
    """Static only: no dataset, tensor, optimizer, model, scheduler or output write."""
    require_registered_config(config)
    package = Path(__file__).resolve().parent
    source = source_inventory(package)
    for name in source:
        ast.parse((package / name).read_text(encoding="utf-8-sig"), filename=name)
    return {"schema": 1, "protocol_id": PROTOCOL_ID, "source_parses": True,
            "source_sha256": source, "project_path": str(root), "validation_level": "V0_static",
            "scientific_execution_performed": False, "training_performed": False,
            "data_read": False, "execution_authorized": False,
            "claims_supported": False, "data_prerequisites_checked": False}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    operation = parser.add_mutually_exclusive_group(required=True)
    operation.add_argument("--check", action="store_true")
    operation.add_argument("--allow-research-execution", action="store_true")
    parser.add_argument("--resume-checkpoint", type=Path)
    parser.add_argument("--checkpoint-sha256")
    parser.add_argument("--target")
    parser.add_argument("--method")
    parser.add_argument("--seed", type=int)
    options = parser.parse_args(argv)
    root = options.project.resolve(strict=True)
    path = options.config.resolve(strict=True)
    if (not path.is_relative_to(root) or options.config.is_symlink() or path.stat().st_nlink > 1
            or any(parent.is_symlink() for parent in options.config.parents)):
        raise ProtocolError("Configuration must be a current owned project file")
    config = yaml.safe_load(path.read_text(encoding="utf-8-sig"))
    resume = (options.resume_checkpoint, options.checkpoint_sha256, options.target, options.method, options.seed)
    if any(value is not None for value in resume) and (not all(value is not None for value in resume) or options.check):
        raise ProtocolError("Condition resume requires execution consent, checkpoint hash and complete target/method/seed identity")
    if options.check:
        report = source_check(root, config)
    else:
        from .study import run_study, resume_condition

        report = (resume_condition(root, config, {"path": options.resume_checkpoint, "sha256": options.checkpoint_sha256,
                  "target": options.target, "method": options.method, "seed": options.seed}, allow_execution=True)
                  if options.resume_checkpoint else run_study(root, config, allow_execution=True))
    print(json.dumps(report, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
