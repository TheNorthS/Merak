"""Reconcile accepted reviewer edits with staged manuscript state."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Callable

from ..utils.atomic_write import atomic_write_text
from .manuscript_text import read_owned_state, sha256, write_json
from .paper_stage_validator_signature import stage_validator_signature


def reconcile_reviewed_artifacts(
    project_path: str | Path,
    *,
    reviewer: str,
    paths: dict[str, Path],
    draft_schema: int,
    author_order: tuple[str, ...],
    consistency_version: int,
    assembly_version: int,
    validate_stage: Callable[[str | Path, str], dict[str, Any]],
    validate_complete: Callable[..., dict[str, Any]],
    assemble: Callable[[str | Path], Path],
    stage_outputs: Callable[[dict[str, Path], str], list[Path]],
    input_signature: Callable[[dict[str, Path], str], str],
    contract_version: Callable[[str], int],
) -> dict[str, Any]:
    state = read_owned_state(paths["state"])
    if state.get("schema_version") != draft_schema:
        return {"passed": False, "issues": [
            "paper/DRAFT_STATE.json is missing or unsupported"
        ]}
    stage_reviews = _validate_authored_stages(
        project_path, author_order, validate_stage
    )
    if stage_reviews["issues"]:
        return {"passed": False, "issues": stage_reviews["issues"]}
    complete = validate_complete(project_path, require_main=False)
    if not complete.get("passed"):
        return {"passed": False, "issues": list(complete.get("issues") or [])}
    evidence_mode = str(complete.get("evidence_mode") or "design_only")
    _write_cross_review(paths["cross_review"], evidence_mode)
    consistency_review = validate_stage(project_path, "consistency")
    if not consistency_review.get("passed"):
        return {"passed": False, "issues": list(consistency_review.get("issues") or [])}
    main_path = assemble(project_path)
    final = validate_complete(project_path)
    if not final.get("passed"):
        return {"passed": False, "issues": list(final.get("issues") or [])}
    _commit_reconciled_state(
        state, paths, stage_reviews["reviews"], consistency_review,
        reviewer, main_path, author_order, consistency_version, assembly_version,
        stage_outputs, input_signature, contract_version,
    )
    return {
        "passed": True, "issues": [], "main_path": str(main_path),
        "main_sha256": sha256(main_path), "evidence_mode": evidence_mode,
        "reviewer": reviewer,
    }


def _validate_authored_stages(
    project_path: str | Path, author_order: tuple[str, ...],
    validate_stage: Callable[[str | Path, str], dict[str, Any]],
) -> dict[str, Any]:
    reviews: dict[str, dict[str, Any]] = {}
    for stage in author_order:
        if stage == "consistency":
            continue
        review = validate_stage(project_path, stage)
        reviews[stage] = review
        if not review.get("passed"):
            return {
                "reviews": reviews,
                "issues": [f"{stage}: {item}" for item in review.get("issues", [])],
            }
    return {"reviews": reviews, "issues": []}


def _write_cross_review(path: Path, evidence_mode: str) -> None:
    atomic_write_text(path, "\n".join([
        "# Checks Performed", "",
        "- Revalidated every canonical section against its local contract.",
        "- Rechecked citation keys, labels, references, terminology, and evidence language.",
        "- Rechecked manuscript length, duplicated prose, and cross-section consistency.",
        "", "# Edits Applied", "",
        "- Reconciled targeted edits with staged state; reviewer provenance is retained.",
        "", "# Remaining Evidence Gaps", "",
        f"- Evidence mode remains `{evidence_mode}`; this PASS certifies consistency, not new empirical evidence.",
        "", "# Final Consistency Verdict", "", "PASS", "",
    ]))


def _commit_reconciled_state(
    state: dict[str, Any], paths: dict[str, Path],
    stage_reviews: dict[str, dict[str, Any]], consistency_review: dict[str, Any],
    reviewer: str, main_path: Path, author_order: tuple[str, ...],
    consistency_version: int, assembly_version: int,
    stage_outputs: Callable[[dict[str, Path], str], list[Path]],
    input_signature: Callable[[dict[str, Path], str], str],
    contract_version: Callable[[str], int],
) -> None:
    now = time.time()
    reviews = read_owned_state(paths["reviews"])
    reviews.setdefault("schema_version", 1)
    reviews.setdefault("sections", {})
    for stage, review in stage_reviews.items():
        record = dict(state.setdefault("stages", {}).get(stage) or {})
        attempt = max(1, int(record.get("attempts") or 0))
        reviews["sections"][stage] = _review_record(
            review, attempt, now, f"deterministic:post-{reviewer}"
        )
        _complete_stage_record(
            record, paths, stage, attempt, now, stage_outputs,
            input_signature, contract_version(stage),
        )
        state["stages"][stage] = record
    _commit_consistency(
        state, reviews, paths, consistency_review, reviewer, now,
        consistency_version, stage_outputs, input_signature,
    )
    _commit_assembly(state, assembly_version, now)
    state.update({
        "status": "completed", "main_sha256": sha256(main_path),
        "completed_at": now, "updated_at": now,
    })
    write_json(paths["reviews"], reviews)
    write_json(paths["state"], state)


def _review_record(
    review: dict[str, Any], attempt: int, now: float, reviewer: str
) -> dict[str, Any]:
    return {**review, "attempt": attempt, "reviewed_at": now, "reviewer": reviewer}


def _complete_stage_record(
    record: dict[str, Any], paths: dict[str, Path], stage: str,
    attempt: int, now: float,
    stage_outputs: Callable[[dict[str, Path], str], list[Path]],
    input_signature: Callable[[dict[str, Path], str], str], version: int,
) -> None:
    record.update({
        "status": "completed", "attempts": attempt, "review_passed": True,
        "review_issues": [],
        "output_hashes": {path.name: sha256(path) for path in stage_outputs(paths, stage)
                          if path.is_file()},
        "input_signature": input_signature(paths, stage),
        "validator_signature": stage_validator_signature(stage),
        "contract_version": version, "updated_at": now, "completed_at": now,
    })
    record.pop("error", None)


def _commit_consistency(
    state: dict[str, Any], reviews: dict[str, Any], paths: dict[str, Path],
    review: dict[str, Any], reviewer: str, now: float, version: int,
    stage_outputs: Callable[[dict[str, Path], str], list[Path]],
    input_signature: Callable[[dict[str, Path], str], str],
) -> None:
    record = dict(state.setdefault("stages", {}).get("consistency") or {})
    attempt = max(1, int(record.get("attempts") or 0))
    reviews["cross_section"] = _review_record(
        review, attempt, now, f"deterministic:post-{reviewer}"
    )
    _complete_stage_record(
        record, paths, "consistency", attempt, now,
        stage_outputs, input_signature, version,
    )
    state["stages"]["consistency"] = record


def _commit_assembly(state: dict[str, Any], version: int, now: float) -> None:
    record = dict(state.setdefault("stages", {}).get("assembly") or {})
    record.update({
        "status": "completed", "attempts": max(1, int(record.get("attempts") or 0)),
        "review_passed": True, "review_issues": [], "contract_version": version,
        "updated_at": now, "completed_at": now,
    })
    record.pop("error", None)
    state["stages"]["assembly"] = record


def refresh_deterministic_assembly(
    project_path: str | Path,
    *,
    paths: dict[str, Path], draft_schema: int, author_order: tuple[str, ...],
    assembly_version: int,
    stage_is_current: Callable[[dict[str, Path], dict[str, Any], str], bool],
    assemble: Callable[[str | Path], Path],
    validate_complete: Callable[..., dict[str, Any]],
) -> dict[str, Any]:
    state = read_owned_state(paths["state"])
    if state.get("schema_version") != draft_schema:
        return {"passed": False, "issues": [
            "paper/DRAFT_STATE.json is missing or unsupported"
        ]}
    stale = [stage for stage in author_order if not stage_is_current(paths, state, stage)]
    if stale:
        return {"passed": False, "issues": [
            "reviewed paper stages are stale: " + ", ".join(stale)
        ]}
    main_path = assemble(project_path)
    final = validate_complete(project_path)
    if not final.get("passed"):
        return {"passed": False, "issues": list(final.get("issues") or [])}
    state = read_owned_state(paths["state"])
    now = time.time()
    _commit_assembly(state, assembly_version, now)
    state.update({
        "status": "completed", "main_sha256": sha256(main_path),
        "completed_at": state.get("completed_at") or now, "updated_at": now,
    })
    write_json(paths["state"], state)
    return {
        "passed": True, "issues": [], "main_path": str(main_path),
        "main_sha256": state["main_sha256"],
    }
