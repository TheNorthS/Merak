"""Validate managed output ownership without executing experiment source."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from typing import Any


OwnedArtifacts = dict[str, dict[str, Any]]
MatchedArtifacts = dict[str, tuple[str, dict[str, Any]]]


def _manifest_state(manifest: dict[str, Any]) -> tuple[OwnedArtifacts, list[str]]:
    attempts = [
        item for item in manifest.get("attempts") or [] if isinstance(item, dict)
    ]
    current = int(manifest.get("current_attempt") or 0)
    attempt = next(
        (item for item in attempts if int(item.get("attempt") or 0) == current), {}
    )
    issues: list[str] = []
    for label, record in (
        ("managed run manifest", manifest),
        ("current managed attempt", attempt),
    ):
        status = str(record.get("status") or "").casefold()
        if status != "completed":
            issues.append(f"{label} is not completed: {status or 'unknown'}")
    if (
        manifest.get("evidence_eligible") is False
        or attempt.get("evidence_eligible") is False
    ):
        issues.append("current managed attempt is explicitly ineligible as evidence")
    artifacts = (
        attempt.get("result_artifacts") or manifest.get("result_artifacts") or {}
    )
    return (artifacts if isinstance(artifacts, dict) else {}), issues


def _expected_files(run_spec: dict[str, Any]) -> list[str]:
    outputs = run_spec.get("outputs") or {}
    outputs = outputs if isinstance(outputs, dict) else {}
    expected = outputs.get("per_run_files") or []
    if not isinstance(expected, list):
        raise ValueError("RUN_SPEC.outputs.per_run_files must be a list")
    paths = [
        str(item).replace("\\", "/").strip() for item in expected if str(item).strip()
    ]
    return paths or [
        str(value).replace("\\", "/").strip()
        for key, value in outputs.items()
        if key not in {"base_dir", "analysis_files", "per_run_files"}
        and isinstance(value, str)
        and Path(value).suffix
    ]


def _match_output(
    artifacts: OwnedArtifacts, declared: str
) -> tuple[str, dict[str, Any]] | None:
    candidates = [
        (str(relative), facts)
        for relative, facts in artifacts.items()
        if isinstance(facts, dict)
        and (
            str(relative).replace("\\", "/") == declared
            or str(relative).replace("\\", "/").endswith("/" + declared)
            or ("/" not in declared and Path(str(relative)).name == declared)
        )
    ]
    return (
        max(candidates, key=lambda item: float(item[1].get("mtime") or 0))
        if candidates
        else None
    )


def _owned_stat_issues(path: Path, relative: str, facts: dict[str, Any]) -> list[str]:
    current = path.stat()
    issues: list[str] = []
    if facts.get("bytes") is not None:
        try:
            if int(facts["bytes"]) != current.st_size:
                issues.append(
                    "declared output size no longer matches the current attempt: "
                    + relative
                )
        except (TypeError, ValueError):
            issues.append(
                f"declared output has an invalid owned byte count: {relative}"
            )
    if facts.get("mtime") is not None:
        try:
            if abs(float(facts["mtime"]) - current.st_mtime) > 0.001:
                issues.append(
                    "declared output modification time no longer matches the current attempt: "
                    + relative
                )
        except (TypeError, ValueError):
            issues.append(
                f"declared output has an invalid owned modification time: {relative}"
            )
    return issues


def _owned_hash_issues(
    path: Path,
    relative: str,
    facts: dict[str, Any],
    direct_hash_limit: int,
) -> list[str]:
    owned_hash = str(facts.get("sha256") or "").strip()
    if not owned_hash:
        return [f"declared output has no current-attempt sha256 ownership: {relative}"]
    if path.stat().st_size > direct_hash_limit:
        return []
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as error:
        return [
            f"declared output hash could not be verified ({relative}): {type(error).__name__}: {error}"
        ]
    if digest.hexdigest() != owned_hash:
        return [
            "declared output content no longer matches the current-attempt sha256: "
            + relative
        ]
    return []


def _tabular_issues(path: Path, relative: str) -> list[str]:
    with path.open("r", encoding="utf-8-sig", errors="strict", newline="") as handle:
        reader = csv.reader(
            handle, delimiter="\t" if path.suffix.casefold() == ".tsv" else ","
        )
        header, first_row = next(reader, []), next(reader, [])
    issues = []
    if not any(str(item).strip() for item in header):
        issues.append(f"tabular output has no header: {relative}")
    if not any(str(item).strip() for item in first_row):
        issues.append(f"tabular output has no data rows: {relative}")
    return issues


def _parse_output_issues(path: Path, relative: str) -> list[str]:
    suffix = path.suffix.casefold()
    try:
        if suffix in {".csv", ".tsv"}:
            return _tabular_issues(path, relative)
        if suffix == ".json":
            json.loads(path.read_text(encoding="utf-8-sig", errors="strict"))
        elif suffix == ".jsonl":
            with path.open("r", encoding="utf-8-sig", errors="strict") as handle:
                first = next((line for line in handle if line.strip()), "")
            if not first:
                return [f"JSONL output has no records: {relative}"]
            json.loads(first)
        elif suffix in {".yaml", ".yml"}:
            return _yaml_output_issues(path, relative)
    except (OSError, UnicodeError, csv.Error, json.JSONDecodeError) as error:
        return [
            f"declared output is not parseable ({relative}): {type(error).__name__}: {error}"
        ]
    return []


def _yaml_output_issues(path: Path, relative: str) -> list[str]:
    try:
        import yaml
    except ImportError as error:
        return [
            f"declared output parser failed ({relative}): {type(error).__name__}: {error}"
        ]
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8-sig", errors="strict"))
    except yaml.YAMLError as error:
        return [
            f"declared output parser failed ({relative}): {type(error).__name__}: {error}"
        ]
    return [f"YAML output has no document: {relative}"] if document is None else []


def _owned_file_issues(
    root: Path,
    relative: str,
    facts: dict[str, Any],
    direct_hash_limit: int,
) -> list[str]:
    path = (root / relative).resolve()
    if not path.is_relative_to(root):
        return [f"declared output escapes the project root: {relative}"]
    if not path.is_file():
        return [f"declared output file is missing: {relative}"]
    if path.stat().st_size <= 0:
        return [f"declared output file is empty: {relative}"]
    return [
        *_owned_stat_issues(path, relative, facts),
        *_owned_hash_issues(path, relative, facts, direct_hash_limit),
        *_parse_output_issues(path, relative),
    ]


def _provenance_issues(
    root: Path, matched: MatchedArtifacts, expected: list[str]
) -> list[str]:
    provenance_matches = [
        value
        for declared, value in matched.items()
        if Path(declared).name.casefold() == "provenance.json"
    ]
    if not provenance_matches:
        return (
            ["declared provenance.json is unavailable for hash validation"]
            if any(Path(item).name.casefold() == "provenance.json" for item in expected)
            else []
        )
    path = (root / provenance_matches[0][0]).resolve()
    if not path.is_relative_to(root):
        return ["declared provenance.json escapes the project root"]
    try:
        provenance = json.loads(path.read_text(encoding="utf-8-sig", errors="strict"))
        if not isinstance(provenance, dict):
            return ["provenance.json root must be a JSON object"]
        hashes = provenance.get("result_file_sha256") or {}
        hashes = (
            {str(value) for value in hashes.values()}
            if isinstance(hashes, dict)
            else set()
        )
        return [
            "provenance.json does not bind the declared output hash: " + declared
            for declared, (_, facts) in matched.items()
            if Path(declared).name.casefold() != "provenance.json"
            and str(facts.get("sha256") or "")
            and str(facts.get("sha256") or "") not in hashes
        ]
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        return [f"provenance.json cannot be validated: {type(error).__name__}: {error}"]


def managed_output_issues(
    root: Path,
    run_spec: dict[str, Any],
    job: Any,
    *,
    direct_hash_limit: int = 64 * 1024 * 1024,
) -> list[str]:
    root = root.resolve()
    if run_spec.get("scheduled_runs"):
        from ..services.execution_cell_binding import resolve_cell_spec
        try:
            run_spec = resolve_cell_spec(root, run_spec, job)
        except (OSError, ValueError, TypeError) as error:
            return [f"Managed matrix cell binding is invalid: {error}"]
    manifest_value = (
        job if isinstance(job, (str, Path)) else getattr(job, "manifest_path", "")
    )
    manifest_path = Path(str(manifest_value or ""))
    if not manifest_path.is_file():
        return [f"managed run manifest is missing: {manifest_path}"]
    try:
        manifest = json.loads(
            manifest_path.read_text(encoding="utf-8-sig", errors="strict")
        )
        if not isinstance(manifest, dict):
            return ["managed run manifest root must be a JSON object"]
        artifacts, issues = _manifest_state(manifest)
        expected = _expected_files(run_spec)
    except (
        OSError,
        UnicodeError,
        json.JSONDecodeError,
        TypeError,
        ValueError,
    ) as error:
        return [f"managed run manifest is invalid: {type(error).__name__}: {error}"]
    if not expected:
        return ["RUN_SPEC.outputs does not declare any per-run evidence files"]
    matched: MatchedArtifacts = {}
    for declared in expected:
        try:
            match = _match_output(artifacts, declared)
        except (TypeError, ValueError) as error:
            issues.append(
                f"declared output has invalid ownership metadata ({declared}): {error}"
            )
            continue
        if match is None:
            issues.append(
                f"declared output is not hash-owned by the current attempt: {declared}"
            )
            continue
        relative, facts = match
        matched[declared] = match
        try:
            issues.extend(_owned_file_issues(root, relative, facts, direct_hash_limit))
        except OSError as error:
            issues.append(
                f"declared output could not be inspected ({relative}): {error}"
            )
    issues.extend(_provenance_issues(root, matched, expected))
    return list(dict.fromkeys(issues))
