"""Structured gate report for the staged manuscript workflow."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Optional

from .manuscript_text import read_json, read_owned_state, sha256
from .paper_stage_validator_signature import stage_validator_signature


def gate_report(
    project_path: str | Path,
    options: Optional[dict[str, Any]],
    *,
    paths: dict[str, Path],
    draft_schema: int,
    author_order: tuple[str, ...],
    assembly_version: int,
    stage_labels: dict[str, str],
    venue_bundles: dict[str, dict[str, Any]],
    stage_is_current: Callable[[dict[str, Path], dict[str, Any], str], bool],
    stage_outputs: Callable[[dict[str, Path], str], list[Path]],
    stage_contract_version: Callable[[str], int],
    target_signature: Callable[[dict[str, Path], str], str],
    issue_signature: Callable[[list[str]], str],
    gate_options: Callable[[Optional[dict[str, Any]], Optional[dict[str, Any]]], dict[str, Any]],
    validate_freeze: Callable[[str | Path, Optional[dict[str, Any]]], dict[str, Any]],
    source_signature: Callable[[str | Path, Optional[dict[str, Any]]], str],
    authoring_signature: Callable[[str | Path, Optional[dict[str, Any]]], str],
    canonical_venue: Callable[[Any], str],
    canonical_family: Callable[[str, dict[str, Any]], str],
    template_fingerprint: Callable[[str | Path], str],
    validate_complete: Callable[..., dict[str, Any]],
) -> dict[str, Any]:
    state = read_owned_state(paths["state"])
    reviews = read_owned_state(paths["reviews"])
    active = _active_stage(
        paths, state, author_order, assembly_version,
        stage_is_current, stage_contract_version,
    )
    target_files, findings = _active_findings(
        paths, active, author_order, stage_labels, stage_outputs,
        stage_contract_version, target_signature, issue_signature,
    )
    signature_options = gate_options(
        options,
        state.get("authoring_options")
        if isinstance(state.get("authoring_options"), dict) else None,
    )
    issues = _state_issues(
        project_path, paths, state, reviews, draft_schema, author_order,
        signature_options, stage_is_current, stage_contract_version,
        validate_freeze, source_signature, authoring_signature,
    )
    issues.extend(_template_issues(
        paths, state, venue_bundles, canonical_venue,
        canonical_family, template_fingerprint,
    ))
    assembly = dict(state.get("stages", {}).get("assembly") or {})
    complete = validate_complete(
        project_path, require_main=assembly.get("status") == "completed"
    )
    issues.extend(complete["issues"])
    from .paper_consistency_findings import merge_complete_findings

    if active["stage"] in {"consistency", "assembly", ""}:
        findings = merge_complete_findings(findings, list(complete.get("findings") or []))
    target_files = list(dict.fromkeys(target for item in findings for target in item.get("target_files") or []))
    return {
        **complete,
        "passed": not issues,
        "issues": list(dict.fromkeys(issues)),
        "state_path": str(paths["state"]),
        "reviews_path": str(paths["reviews"]),
        "contracts_path": str(paths["contracts"]),
        "style_profile_path": str(paths["style"]),
        "publication_class": str(state.get("publication_class") or "scientific_draft"),
        "active_stage": active["stage"],
        "active_stage_label": stage_labels.get(active["stage"], active["stage"]),
        "findings": findings,
        "target_files": target_files,
        "semantic_no_progress": any(bool(item.get("semantic_no_progress")) for item in findings),
    }


def _active_stage(
    paths: dict[str, Path], state: dict[str, Any], author_order: tuple[str, ...],
    assembly_version: int,
    stage_is_current: Callable[[dict[str, Path], dict[str, Any], str], bool],
    contract_version: Callable[[str], int],
) -> dict[str, Any]:
    for stage in author_order:
        record = dict(state.get("stages", {}).get(stage) or {})
        from .paper_deferred_rebind import deferred_rebind_current
        if deferred_rebind_current(paths, state, stage):
            continue
        if (record.get("status") != "completed" or not record.get("review_passed")
                or not stage_is_current(paths, state, stage)):
            return {"stage": stage, "record": record}
    assembly = dict(state.get("stages", {}).get("assembly") or {})
    if assembly.get("status") != "completed" or assembly.get("contract_version") != assembly_version:
        return {"stage": "assembly", "record": assembly}
    return {"stage": "", "record": {}}


def _active_findings(
    paths: dict[str, Path], active: dict[str, Any], author_order: tuple[str, ...],
    labels: dict[str, str], stage_outputs: Callable[[dict[str, Path], str], list[Path]],
    contract_version: Callable[[str], int],
    target_signature: Callable[[dict[str, Path], str], str],
    issue_signature: Callable[[list[str]], str],
) -> tuple[list[str], list[dict[str, Any]]]:
    stage, record = active["stage"], active["record"]
    if not stage:
        return [], []
    targets = stage_outputs(paths, stage) if stage in author_order else [paths["main"]]
    target_files = [_relative_target(path, paths["root"]) for path in targets]
    target_files = list(dict.fromkeys(target_files))
    issues = _active_stage_issues(stage, record, labels, contract_version)
    artifact_signature = target_signature(paths, stage)
    findings = []
    for issue in issues:
        signature = issue_signature([issue])
        label = labels.get(stage, stage)
        findings.append({
            "id": f"PAPER-STAGE-{stage.upper()}-{signature[:10].upper()}",
            "severity": "blocker", "category": "paper_section",
            "message": f"{label}: {issue}", "plain_message": f"{label}: {issue}",
            "remediation": f"Revise only {label} and its declared target artifacts; preserve every already accepted section.",
            "owner_node": "paper", "upstream_node": "paper", "stage_id": stage,
            "target_files": target_files, "issue_signature": signature,
            "artifact_signature": artifact_signature,
            "semantic_no_progress": str(record.get("error") or "").startswith("semantic no-progress:"),
        })
    return target_files, findings


def _relative_target(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root).as_posix()
    except (OSError, ValueError):
        return str(path)


def _active_stage_issues(
    stage: str, record: dict[str, Any], labels: dict[str, str],
    contract_version: Callable[[str], int],
) -> list[str]:
    issues = [str(item).strip() for item in record.get("review_issues", [])
              if str(item).strip()]
    if issues:
        return issues
    error = str(record.get("error") or "").strip()
    if error and not error.startswith("semantic no-progress:"):
        return [error]
    label = labels.get(stage, stage)
    if record.get("contract_version") != contract_version(stage):
        return [f"{label} requires deterministic revalidation under the current paper contract."]
    if (record.get("status") == "completed" and record.get("review_passed")
            and record.get("validator_signature") != stage_validator_signature(stage)):
        return [f"{label} requires deterministic revalidation under the current paper validator."]
    if stage == "assembly":
        return ["Missing or empty paper/main.tex because deterministic assembly has not completed."]
    return [f"{label} has not passed its local section contract."]


def _state_issues(
    project_path: str | Path, paths: dict[str, Path], state: dict[str, Any],
    reviews: dict[str, Any], draft_schema: int, author_order: tuple[str, ...],
    options: dict[str, Any],
    stage_is_current: Callable[[dict[str, Path], dict[str, Any], str], bool],
    contract_version: Callable[[str], int],
    validate_freeze: Callable[[str | Path, Optional[dict[str, Any]]], dict[str, Any]],
    source_signature: Callable[[str | Path, Optional[dict[str, Any]]], str],
    authoring_signature: Callable[[str | Path, Optional[dict[str, Any]]], str],
) -> list[str]:
    issues = []
    if state.get("schema_version") != draft_schema:
        issues.append("paper/DRAFT_STATE.json is missing or unsupported")
    freeze = validate_freeze(project_path, options)
    issues.extend(freeze.get("issues") or [])
    if freeze.get("passed") and state.get("scientific_freeze_id") != freeze.get("freeze_id"):
        issues.append("staged paper state is bound to a different scientific freeze")
    if (state.get("source_signature") != source_signature(project_path, options)
            and state.get("authoring_signature") != authoring_signature(project_path, options)):
        issues.append("staged paper state is stale relative to scientific inputs")
    _phase_issues(paths, state, reviews, author_order, contract_version, stage_is_current, issues)
    if state.get("explanation_refresh_requires_model_review"):
        issues.append("changed scientific explanation requires fresh independent cross-section model review")
    assembly = dict(state.get("stages", {}).get("assembly") or {})
    if assembly.get("status") == "completed":
        from .paper_print_projection import assembled_print_sha256
        try:
            if state.get('main_sha256') != assembled_print_sha256(paths['root']):
                issues.append('main.tex does not match reviewed deterministic assembly')
        except ValueError as error:
            issues.append(str(error))
    return issues


def _phase_issues(
    paths: dict[str, Path], state: dict[str, Any], reviews: dict[str, Any],
    author_order: tuple[str, ...], contract_version: Callable[[str], int],
    stage_is_current: Callable[[dict[str, Path], dict[str, Any], str], bool],
    issues: list[str],
) -> None:
    for stage in (*author_order, "assembly"):
        record = dict(state.get("stages", {}).get(stage) or {})
        if record.get("status") != "completed":
            issues.append(f"incomplete staged paper phase: {stage}")
        if record.get("contract_version") != contract_version(stage):
            issues.append(f"staged paper phase uses an outdated contract: {stage}")
        if stage != "assembly" and not record.get("review_passed"):
            issues.append(f"stage has no passing local review: {stage}")
    if not dict(reviews.get("cross_section") or {}).get("passed"):
        issues.append("cross-section consistency review is missing or failing")
    for stage in author_order:
        record = dict(state.get("stages", {}).get(stage) or {})
        from .paper_deferred_rebind import deferred_rebind_current
        if (record.get("status") == "completed" and not stage_is_current(paths, state, stage)
                and not deferred_rebind_current(paths, state, stage)):
            issues.append(f"artifact changed after review: {stage}")


def _template_issues(
    paths: dict[str, Path], state: dict[str, Any],
    bundles: dict[str, dict[str, Any]], canonical_venue: Callable[[Any], str],
    canonical_family: Callable[[str, dict[str, Any]], str],
    fingerprint: Callable[[str | Path], str],
) -> list[str]:
    issues = []
    venue_key = canonical_venue(state.get("target_venue"))
    metadata = dict(state.get("venue_template") or {})
    template_path = str(
        state.get("venue_template_path")
        or dict(state.get("authoring_options") or {}).get("venue_template_path") or ""
    ).strip()
    if template_path:
        _custom_template_issues(paths, metadata, template_path, fingerprint, issues)
    elif venue_key:
        if metadata.get("key") != venue_key:
            issues.append(f"target venue {venue_key} was not assembled with its bundled review template")
        for filename in bundles[venue_key]["assets"]:
            asset = paths["paper"] / filename
            if not asset.is_file() or asset.stat().st_size == 0:
                issues.append(f"target venue template asset is missing: {filename}")
    else:
        style = read_json(paths["style"])
        expected = canonical_family(
            str(state.get("target_venue") or ""),
            dict(style.get("publication_visual_style") or {}),
        )
        if metadata.get("key") != expected or metadata.get("mode") != "venue_family_policy":
            issues.append("manuscript was not assembled with the selected field/venue template policy")
    return issues


def _custom_template_issues(
    paths: dict[str, Path], metadata: dict[str, Any], template_path: str,
    fingerprint: Callable[[str | Path], str], issues: list[str],
) -> None:
    if metadata.get("key") != "custom" or metadata.get("mode") != "user_supplied_template":
        issues.append("user-supplied venue template was not used during assembly")
    source = Path(template_path).expanduser()
    current = fingerprint(source)
    if source.exists() and current and metadata.get("source_sha256") != current:
        issues.append("user-supplied venue template changed after manuscript assembly")
    snapshot = paths["paper"] / str(metadata.get("snapshot_directory") or "venue_template")
    if not snapshot.is_dir() or not any(snapshot.rglob("*")):
        issues.append("user-supplied venue template snapshot is missing")
    for relative in metadata.get("assets", []):
        asset = (paths["paper"] / str(relative)).resolve()
        if (not asset.is_relative_to(paths["paper"].resolve()) or not asset.is_file()
                or asset.stat().st_size == 0):
            issues.append(f"user-supplied venue template asset is missing: {relative}")
