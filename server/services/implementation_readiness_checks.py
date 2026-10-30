"""Source-bound readiness and declared CLI validation without executing research code."""
from __future__ import annotations

import ast
import shlex
from pathlib import Path
from typing import Any

from ..contracts.entrypoints import python_entrypoint_refs
from ..contracts.implementation_readiness import ImplementationReadiness


def _finding(identity: str, message: str, targets: list[str], stage: str = "integration") -> dict:
    return {"id": identity, "severity": "blocker", "category": "implementation",
            "message": message, "plain_message": message, "target_files": targets,
            "owner_node": "exp-design", "upstream_node": "exp-design", "stage_id": stage,
            "remediation": "Repair the owning stage and revalidate the declared contract before finalization."}


def readiness_findings(root: Path, spec: dict[str, Any]) -> list[dict]:
    findings = []
    status = str(spec.get("status") or "").casefold()
    if status.startswith("integration_blocked") and not spec.get("integration_blockers"):
        findings.append(_finding("IMPL-READINESS-STATUS", "RUN_SPEC declares blocked integration without actionable blockers",
                                 ["experiments/RUN_SPEC.json"]))
    if "integration_readiness" in spec or "integration_blockers" in spec:
        try:
            declaration = ImplementationReadiness.model_validate(spec)
        except ValueError as error:
            return [_finding("IMPL-READINESS-SCHEMA", str(error), ["experiments/RUN_SPEC.json"])]
        for blocker in declaration.integration_blockers:
            path = (root / blocker.path).resolve()
            if not path.is_relative_to(root.resolve()) or not blocker.path.startswith("experiments/src/"):
                targets = ["experiments/RUN_SPEC.json"]
            else:
                targets = [blocker.path, "experiments/RUN_SPEC.json"]
            findings.append(_finding(f"IMPL-DECLARED-{blocker.id}", blocker.description, targets, blocker.owner))
        if declaration.integration_readiness != "ready" and not findings:
            findings.append(_finding("IMPL-READINESS-BLOCKED",
                f"RUN_SPEC.integration_readiness={declaration.integration_readiness}; implementation is not ready",
                ["experiments/RUN_SPEC.json"]))
    return findings + command_findings(root, spec)


def _cli_options(tree: ast.Module) -> set[str] | None:
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)]
    if not any(isinstance(n.func, ast.Attribute) and n.func.attr == "parse_args" for n in calls):
        return None  # Other CLI frameworks require their own adapter, not invented argparse rules.
    return {a.value for n in calls if isinstance(n.func, ast.Attribute) and n.func.attr == "add_argument"
            for a in n.args if isinstance(a, ast.Constant) and isinstance(a.value, str) and a.value.startswith("-")}


def command_findings(root: Path, spec: dict[str, Any]) -> list[dict]:
    findings = []
    for field in ("command", "scientific_command", "execution_command", "preflight_command",
                  "aggregate_command", "aggregation_command", "evaluation_command"):
        command = spec.get(field)
        if not isinstance(command, str) or not command.strip():
            continue
        refs = python_entrypoint_refs([command])
        if len(refs) != 1:
            continue
        path = refs[0].resolve(root)
        try:
            options = _cli_options(ast.parse(path.read_text(encoding="utf-8-sig")))
            tokens = shlex.split(command, posix=True)
        except (OSError, ValueError, SyntaxError):
            continue  # The source parse/entrypoint gate reports these failures.
        if options is None:
            continue
        position = next((i for i, value in enumerate(tokens) if value.replace("\\", "/") == refs[0].serialized), -1)
        if position < 0:
            continue
        declared = {value.split("=", 1)[0] for value in tokens[position + 1:] if value.startswith("--")}
        missing = sorted(declared - options - {"--help"})
        if missing:
            findings.append(_finding(f"IMPL-CLI-{field.upper()}",
                f"RUN_SPEC.{field} declares unsupported entrypoint options: {', '.join(missing)}",
                [refs[0].path.as_posix(), "experiments/RUN_SPEC.json"], "training"))
    return findings
