"""Validate explicit post-failure operator observations of a real native launch.

The original tool result may be conversational rather than a durable launch
JSON. This contract labels that limitation honestly: the source hash is a
current read, not a fabricated at-launch hash, and no past tool list is inferred.
"""

from __future__ import annotations

import ast
from datetime import datetime
from pathlib import Path
import re
from typing import Any

from scripts.full_benchmark_continuation_scope import file_sha256


def _source(path: Path, repository: Path, expected: str) -> Path:
    resolved = path.resolve(strict=True)
    if (path.absolute() != resolved or not resolved.is_relative_to(repository)
            or not resolved.parent.name.startswith("verification-logs-")
            or resolved.suffix != ".py" or resolved.is_symlink() or resolved.stat().st_nlink > 1
            or file_sha256(resolved) != expected):
        raise ValueError("Natural failure launch source is not the exact independently observed private file")
    return resolved


def _literal_pins(path: Path) -> dict[str, str]:
    """Read the actual command-list declaration; never execute a private launcher."""
    tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
    declarations = [node.value for node in ast.walk(tree) if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "command" for target in node.targets)
        and isinstance(node.value, ast.List)]
    if len(declarations) != 1:
        raise ValueError("Natural failure needs one exact literal native command declaration")
    values = [item.value if isinstance(item, ast.Constant) and isinstance(item.value, str) else None
              for item in declarations[0].elts]
    flags = ("--run-id", "--previous-report-sha256", "--previous-state-sha256", "--previous-trace-sha256")
    result = {}
    for flag in flags:
        if values.count(flag) != 1:
            raise ValueError("Natural failure launcher lacks independently observed pin: " + flag)
        position = values.index(flag)
        if position + 1 >= len(values) or not isinstance(values[position + 1], str):
            raise ValueError("Natural failure launcher pin is not a literal: " + flag)
        result[flag.removeprefix("--").replace("-", "_")] = values[position + 1]
    if values.count("--allow-real-models") != 1:
        raise ValueError("Natural failure launch did not declare its existing explicit model consent")
    return result


def validate_launch_observation(value: dict[str, Any], repository: Path,
                                run_id: str, archive_pin: str, trace_pin: str) -> dict:
    """Reject inferred before-pins and falsely complete historical observability."""
    required = {"schema", "kind", "recorded_after_failure", "evidence_source", "recorded_at",
                "launcher_path", "launcher_current_sha256", "source_hash_observability",
                "prelaunch_pins", "launch", "confirmed_inactive_pids", "failure_boundary"}
    if (not isinstance(value, dict) or set(value) != required or type(value.get("schema")) is not int
            or value.get("schema") != 1
            or value.get("kind") != "post_failure_operator_launch_observation"
            or value.get("recorded_after_failure") is not True
            or value.get("evidence_source") != "prior_root_tool_results"
            or value.get("source_hash_observability") != "current_read_only_not_launch_time"
            or value.get("failure_boundary") != "native_resume_prevalidation"
            or any(not isinstance(value.get(name), str) or not value[name] for name in
                   ("launcher_path", "launcher_current_sha256", "recorded_at"))):
        raise ValueError("Natural failure requires an explicit truthful post-failure operator observation")
    source = _source(Path(value["launcher_path"]), repository, value["launcher_current_sha256"])
    pins = _literal_pins(source)
    if (value["prelaunch_pins"] != pins or pins["run_id"] != run_id
            or pins["previous_report_sha256"] != archive_pin or pins["previous_trace_sha256"] != trace_pin
            or any(not re.fullmatch(r"[a-f0-9]{64}", pins[name]) for name in pins if name != "run_id")):
        raise ValueError("Natural failure independent before-launch pins changed")
    _validate_native_launch(value, source)
    return value


def _validate_native_launch(value: dict, source: Path) -> None:
    launch = value["launch"]
    fields = {"launcher_pid", "parent_pid", "base_pid", "base_parent_pid", "created_at_utc", "observed_at_utc", "argv"}
    if (not isinstance(launch, dict) or set(launch) != fields
            or any(type(launch.get(name)) is not int or launch[name] <= 0 for name in fields if name.endswith("pid"))
            or launch["base_parent_pid"] != launch["launcher_pid"]
            or launch["base_pid"] == launch["launcher_pid"]
            or any(not isinstance(launch.get(name), str) for name in ("created_at_utc", "observed_at_utc"))
            or launch["argv"] != ["-B", str(source)]):
        raise ValueError("Natural failure needs the exact observed native process chain and command")
    inactive = value["confirmed_inactive_pids"]
    if (not isinstance(inactive, list) or any(type(pid) is not int or pid <= 0 for pid in inactive)
            or len(inactive) != len(set(inactive))
            or not {launch["launcher_pid"], launch["base_pid"]}.issubset(inactive)):
        raise ValueError("Natural failure lacks independent inactive-process observation")
    created = datetime.fromisoformat(launch["created_at_utc"])
    observed = datetime.fromisoformat(launch["observed_at_utc"])
    recorded = datetime.fromisoformat(value["recorded_at"])
    if (any(item.tzinfo is None or item.utcoffset().total_seconds() != 0 for item in (created, observed, recorded))
            or not created <= observed <= recorded):
        raise ValueError("Natural failure observation must retain actual UTC launch order")
