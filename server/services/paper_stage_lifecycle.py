"""Validation and durable state transitions for paper stages."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Callable

from .manuscript_text import (
    final_consistency_verdict,
    read_json,
    read_owned_state,
    read_text,
    sha256,
    write_json,
)
from .paper_stage_validator_signature import stage_validator_signature

StageOutputs = Callable[[dict[str, Path], str], list[Path]]
InputSignature = Callable[[dict[str, Path], str], str]
ContractVersion = Callable[[str], int]


def validate_stage(
    project_path: str | Path,
    stage_id: str,
    *,
    paths: dict[str, Path],
    section_by_id: dict[str, Any],
    validate_blueprint: Callable[[Path], dict[str, Any]],
    validate_front_matter: Callable[[dict[str, Path], dict[str, Any]], dict[str, Any]],
    validate_complete: Callable[..., dict[str, Any]],
    review_section: Callable[..., dict[str, Any]],
) -> dict[str, Any]:
    contracts = read_json(paths["contracts"])
    evidence = dict(contracts.get("evidence") or {})
    if stage_id == "blueprint":
        return validate_blueprint(paths["blueprint"])
    if stage_id == "front_matter":
        return validate_front_matter(paths, evidence)
    if stage_id == "consistency":
        return _validate_consistency(
            project_path, paths, evidence, validate_complete
        )
    mechanisms = [
        str(item) for item in contracts.get("required_mechanisms", [])
        if str(item).strip()
    ] if stage_id == "method" else []
    review = review_section(
        paths["root"], section_by_id[stage_id], evidence, mechanisms
    )
    from .paper_section_figure_binding import section_figure_binding_issues
    issues = section_figure_binding_issues(paths['root'], section_by_id[stage_id].filename)
    if issues:
        review = {**review, 'passed': False, 'issues': [*review.get('issues', []), *issues]}
    return review


def _validate_consistency(
    project_path: str | Path,
    paths: dict[str, Path],
    evidence: dict[str, Any],
    validate_complete: Callable[..., dict[str, Any]],
) -> dict[str, Any]:
    report = validate_complete(project_path, require_main=False)
    report_text = read_text(paths["cross_review"])
    lower = report_text.casefold()
    issues = list(report["issues"])
    if "checks performed" not in lower:
        issues.append("cross-section report lacks Checks Performed")
    if "final consistency verdict" not in lower:
        issues.append("cross-section report lacks a final verdict")
    verdict = final_consistency_verdict(report_text)
    failed = verdict != "PASS"
    if failed:
        issues.append("cross-section reviewer recorded FAIL")
    return {
        **report,
        "passed": not issues,
        "issues": list(dict.fromkeys(issues)),
        "reviewer_verdict": verdict,
        "reviewer_scope_advisory": False,
        "sha256": sha256(paths["cross_review"]),
    }


def record_review(
    paths: dict[str, Path], stage_id: str, review: dict[str, Any], attempt: int,
    *, section_ids: set[str],
) -> None:
    payload = read_owned_state(paths["reviews"])
    state = read_owned_state(paths["state"])
    payload.setdefault("schema_version", 1)
    payload.setdefault("source_signature", state.get("source_signature", ""))
    if stage_id != "consistency":
        payload.setdefault("sections", {})[stage_id] = _review_record(
            review, attempt, "deterministic:section-contract"
        )
    else:
        payload["cross_section"] = _review_record(
            review, attempt, "deterministic:cross-section-contract"
        )
        _record_consistency_sections(payload, state, review, section_ids)
    write_json(paths["reviews"], payload)


def _review_record(
    review: dict[str, Any], attempt: int, reviewer: str
) -> dict[str, Any]:
    return {
        **review,
        "attempt": attempt,
        "reviewed_at": time.time(),
        "reviewer": reviewer,
    }


def _record_consistency_sections(
    payload: dict[str, Any], state: dict[str, Any],
    review: dict[str, Any], section_ids: set[str],
) -> None:
    for section_id, section_review in dict(review.get("section_reviews") or {}).items():
        if section_id not in section_ids or not isinstance(section_review, dict):
            continue
        attempt = max(
            1,
            int(dict(state.get("stages", {}).get(section_id, {})).get("attempts") or 0),
        )
        payload.setdefault("sections", {})[section_id] = _review_record(
            section_review, attempt, "deterministic:cross-section-contract"
        )


def mark_stage(
    paths: dict[str, Path], stage_id: str, status: str, *,
    attempt: int | None, review: dict[str, Any] | None, error: str,
    section_ids: set[str], author_order: tuple[str, ...],
    section_contract_version: int, stage_outputs: StageOutputs,
    input_signature: InputSignature, contract_version: ContractVersion,
) -> dict[str, Any]:
    state = read_owned_state(paths["state"])
    record = dict(state.setdefault("stages", {}).get(stage_id) or {})
    record["status"] = status
    if attempt is not None:
        record["attempts"] = attempt
    record["updated_at"] = time.time()
    if review is not None:
        record["review_passed"] = bool(review.get("passed"))
        record["review_issues"] = list(review.get("issues") or [])
        if review.get("passed"):
            record["validator_signature"] = stage_validator_signature(stage_id)
        else:
            record.pop("validator_signature", None)
    if stage_id == "consistency" and review is not None:
        record["reviewed_input_signature"] = input_signature(paths, stage_id)
        record["reviewed_report_sha256"] = sha256(paths["cross_review"])
        _apply_consistency_reviews(
            state, paths, review, section_ids, section_contract_version,
            stage_outputs, input_signature,
        )
    if status == "completed":
        record.pop("deferred_input_rebind", None)
        _complete_record(
            record, paths, stage_id, stage_outputs, input_signature, contract_version
        )
        if stage_id == "consistency":
            state.pop("explanation_refresh_requires_model_review", None)
            _refresh_authored_identities(
                state, paths, author_order, stage_outputs,
                input_signature, contract_version,
            )
    elif error:
        record["error"] = error[:2000]
    state["stages"][stage_id] = record
    state["updated_at"] = time.time()
    write_json(paths["state"], state)
    return state


def _apply_consistency_reviews(
    state: dict[str, Any], paths: dict[str, Path], review: dict[str, Any],
    section_ids: set[str], section_contract_version: int,
    stage_outputs: StageOutputs, input_signature: InputSignature,
) -> None:
    reviews = {
        str(section_id): dict(section_review)
        for section_id, section_review in dict(review.get("section_reviews") or {}).items()
        if isinstance(section_review, dict)
    }
    if isinstance(review.get("front_matter"), dict):
        reviews["front_matter"] = dict(review["front_matter"])
    for stage, stage_review in reviews.items():
        if stage not in {*section_ids, "front_matter"}:
            continue
        record = dict(state.setdefault("stages", {}).get(stage) or {})
        passed = bool(stage_review.get("passed"))
        record.update({
            "status": "completed" if passed else "revision_required",
            "review_passed": passed,
            "review_issues": list(stage_review.get("issues") or []),
            "contract_version": section_contract_version,
            "updated_at": time.time(),
        })
        if passed:
            record["validator_signature"] = stage_validator_signature(stage)
            _write_output_identity(record, paths, stage, stage_outputs, input_signature)
            record.pop("error", None)
        else:
            record.pop("validator_signature", None)
            record["error"] = "; ".join(stage_review.get("issues") or [])[:2000]
        state["stages"][stage] = record


def _complete_record(
    record: dict[str, Any], paths: dict[str, Path], stage: str,
    stage_outputs: StageOutputs, input_signature: InputSignature,
    contract_version: ContractVersion,
) -> None:
    record["contract_version"] = contract_version(stage)
    _write_output_identity(record, paths, stage, stage_outputs, input_signature)
    record["completed_at"] = time.time()
    record.pop("error", None)


def _write_output_identity(
    record: dict[str, Any], paths: dict[str, Path], stage: str,
    stage_outputs: StageOutputs, input_signature: InputSignature,
) -> None:
    record["output_hashes"] = {
        path.name: sha256(path)
        for path in stage_outputs(paths, stage)
        if path.is_file()
    }
    record["input_signature"] = input_signature(paths, stage)


def _refresh_authored_identities(
    state: dict[str, Any], paths: dict[str, Path], author_order: tuple[str, ...],
    stage_outputs: StageOutputs, input_signature: InputSignature,
    contract_version: ContractVersion,
) -> None:
    for stage in author_order:
        if stage == "consistency":
            break
        record = dict(state.setdefault("stages", {}).get(stage) or {})
        outputs = stage_outputs(paths, stage)
        if record.get("status") != "completed" or not all(
            path.is_file() and path.stat().st_size > 0 for path in outputs
        ):
            continue
        _write_output_identity(record, paths, stage, stage_outputs, input_signature)
        record.pop("deferred_input_rebind", None)
        record["contract_version"] = contract_version(stage)
        record["updated_at"] = time.time()
        state["stages"][stage] = record
