"""Initialize or resume a staged manuscript transaction."""

from __future__ import annotations

import shutil
import time
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

from ..utils.atomic_write import atomic_write_bytes
from .manuscript_text import read_owned_state, sha256, write_json
from .workflow_user_constraints import USER_CONSTRAINTS_PROMPT_VERSION
from .paper_draft_state import FIGURE_SCOPE_PROMPT_VERSION

StageOutputs = Callable[[dict[str, Path], str], list[Path]]
FreezeInputs = Callable[[str | Path, Optional[dict[str, Any]]], dict[str, Any]]


def prepare_draft_state(
    project_path: str | Path,
    options: Optional[dict[str, Any]],
    *,
    paths: dict[str, Path],
    contracts: dict[str, Any],
    author_stages: Iterable[str],
    stage_outputs: StageOutputs,
    freeze_inputs: FreezeInputs,
    draft_schema: int,
    section_contract: int,
    consistency_contract: int,
    assembly_contract: int,
) -> dict[str, Any]:
    paths["paper"].mkdir(parents=True, exist_ok=True)
    paths["sections"].mkdir(parents=True, exist_ok=True)
    from .paper_candidate_recovery import recover_paper_commits
    for stage in author_stages:
        recover_paper_commits(paths['root'].resolve(), stage)
    previous = read_owned_state(paths["state"])
    signature = str(contracts["source_signature"])
    authoring_signature = str(contracts["authoring_signature"])
    inputs = dict(contracts.get("authoring_inputs") or {})
    authoring_options = dict(contracts.get("authoring_options") or {})
    reuse = _reuse_decision(
        previous, signature, authoring_signature, inputs, authoring_options, draft_schema
    )
    from .paper_explanation_refresh import reset_explanation_reviews
    preserve_candidates = bool(not reuse["reusable"] and previous.get("schema_version") == draft_schema
                               and any(path.is_file() and path.stat().st_size > 0
                                       for stage in author_stages if stage != 'consistency'
                                       for path in stage_outputs(paths, stage)))
    stages = tuple(author_stages)
    if previous and not reuse["reusable"]:
        _archive_stale_outputs(paths, previous, stages, stage_outputs, preserve_authors=True)
    if preserve_candidates:
        reuse["reusable"] = True
        reset_explanation_reviews(previous)
    state = _initialize_state(
        previous if reuse["reusable"] else {}, contracts, options, signature,
        authoring_signature, inputs, authoring_options, stages, draft_schema,
    )
    _invalidate_contract_versions(
        state, stages, section_contract, consistency_contract, assembly_contract
    )
    _reset_literature_refresh(state, reuse)
    write_json(paths["state"], state)
    _write_reviews(paths, previous, reuse, signature, authoring_signature, inputs, authoring_options)
    _copy_bibliography(paths)
    freeze = freeze_inputs(project_path, options)
    state["scientific_freeze_id"] = str(freeze.get("freeze_id") or "")
    state["scientific_freeze_generation"] = int(freeze.get("generation") or 0)
    write_json(paths["state"], state)
    return state




def _reuse_decision(
    previous: dict[str, Any], signature: str, authoring_signature: str,
    inputs: dict[str, str], options: dict[str, Any], schema: int,
) -> dict[str, Any]:
    previous_inputs = dict(previous.get("authoring_inputs") or {})
    prior_options = previous.get("authoring_options") or {}
    if not isinstance(prior_options, dict):
        raise ValueError("Persisted paper authoring_options must be a JSON object")
    current_constraint_contract = bool(
        type(prior_options.get("user_constraints_prompt_version")) is int
        and prior_options.get("user_constraints_prompt_version") == USER_CONSTRAINTS_PROMPT_VERSION
        and options.get("user_constraints_prompt_version") == USER_CONSTRAINTS_PROMPT_VERSION
        and type(prior_options.get("figure_scope_prompt_version")) is int
        and prior_options.get("figure_scope_prompt_version") == FIGURE_SCOPE_PROMPT_VERSION
        and options.get("figure_scope_prompt_version") == FIGURE_SCOPE_PROMPT_VERSION
        and prior_options == options
    )
    changed = {
        key for key in set(previous_inputs) | set(inputs)
        if previous_inputs.get(key) != inputs.get(key)
    }
    literature_only = bool(
        previous.get("schema_version") == schema
        and current_constraint_contract
        and changed and changed <= {"literature/survey.md", "literature/references.bib"}
        and previous.get("authoring_options") == options
        and any(
            dict(record or {}).get("status") == "completed"
            for stage, record in dict(previous.get("stages") or {}).items()
            if stage not in {"consistency", "assembly"}
        )
    )
    reusable = bool(
        previous.get("schema_version") == schema
        and current_constraint_contract
        and (
            previous.get("source_signature") == signature
            or previous.get("authoring_signature") == authoring_signature
            or (previous.get("authoring_inputs") == inputs
                and previous.get("authoring_options") == options)
            or literature_only
        )
    )
    return {
        "reusable": reusable,
        "literature_only": literature_only,
        "literature_content": literature_only and "literature/survey.md" in changed,
    }


def _archive_stale_outputs(
    paths: dict[str, Path], previous: dict[str, Any], stages: tuple[str, ...],
    stage_outputs: StageOutputs, *, preserve_authors: bool = False,
) -> None:
    identity = str(
        previous.get("authoring_signature") or previous.get("source_signature") or "unknown"
    )[:12]
    archive_root = paths["paper"] / "revisions" / f"source_refresh_{identity}"
    for stage in stages:
        for output in stage_outputs(paths, stage):
            if not output.is_file():
                continue
            archived = archive_root / output.relative_to(paths["paper"])
            if archived.exists() and sha256(archived) != sha256(output):
                archived = archived.with_name(
                    f"{archived.stem}_{sha256(output)[:12]}{archived.suffix}"
                )
            archived.parent.mkdir(parents=True, exist_ok=True)
            if not archived.exists():
                shutil.copy2(output, archived)
            if not preserve_authors or stage == "consistency":
                output.unlink()


def _initialize_state(
    state: dict[str, Any], contracts: dict[str, Any], options: Optional[dict[str, Any]],
    signature: str, authoring_signature: str, inputs: dict[str, str],
    authoring_options: dict[str, Any], stages: tuple[str, ...], schema: int,
) -> dict[str, Any]:
    state.update({
        "schema_version": schema, "source_signature": signature,
        "authoring_signature": authoring_signature, "authoring_inputs": inputs,
        "authoring_options": authoring_options, "status": "drafting",
        "target_venue": str((options or {}).get("target_venue") or "unspecified"),
        "venue_template_path": str((options or {}).get("venue_template_path") or "").strip(),
        "evidence": contracts["evidence"],
        "publication_class": _publication_class(contracts["evidence"]),
        "stages": dict(state.get("stages") or {}), "updated_at": time.time(),
    })
    for stage in (*stages, "assembly"):
        state["stages"].setdefault(stage, {"status": "pending", "attempts": 0})
    return state


def _publication_class(evidence: dict[str, Any]) -> str:
    if evidence["submission_eligible"]:
        return "submission_candidate"
    if evidence["mode"] == "synthetic_preview":
        return "synthetic_preview"
    return "preregistration_or_scientific_draft"


def _invalidate_contract_versions(
    state: dict[str, Any], stages: tuple[str, ...], section: int,
    consistency: int, assembly: int,
) -> None:
    for stage in stages:
        if stage == "consistency":
            continue
        record = dict(state["stages"].get(stage) or {})
        if record.get("status") == "completed" and record.get("contract_version") != section:
            record.update({"status": "pending", "review_passed": False, "review_issues": []})
            record.pop("error", None)
            state["stages"][stage] = record
    _reset_versioned_record(state, "consistency", consistency)
    _reset_versioned_record(state, "assembly", assembly)


def _reset_versioned_record(state: dict[str, Any], stage: str, version: int) -> None:
    record = dict(state["stages"].get(stage) or {})
    if record.get("contract_version") == version:
        return
    record.update({
        "status": "pending", "attempts": 0, "review_passed": False,
        "review_issues": [], "contract_version": version,
    })
    for key in ("error", "output_hashes", "input_signature", "completed_at"):
        record.pop(key, None)
    state["stages"][stage] = record


def _reset_literature_refresh(state: dict[str, Any], reuse: dict[str, Any]) -> None:
    if not reuse["literature_only"]:
        return
    affected = (
        ("blueprint", "introduction", "related_work", "discussion", "consistency", "assembly")
        if reuse["literature_content"] else ("consistency", "assembly")
    )
    for stage in affected:
        record = dict(state["stages"].get(stage) or {})
        record.update({"status": "pending", "attempts": 0,
                       "review_passed": False, "review_issues": []})
        for key in ("error", "output_hashes", "input_signature", "completed_at"):
            record.pop(key, None)
        state["stages"][stage] = record


def _write_reviews(
    paths: dict[str, Path], previous: dict[str, Any], reuse: dict[str, Any],
    signature: str, authoring_signature: str, inputs: dict[str, str],
    options: dict[str, Any],
) -> None:
    reviews = read_owned_state(paths["reviews"]) if reuse["reusable"] else {}
    if reuse["literature_only"]:
        reviews["cross_section"] = {}
    if previous.get("explanation_refresh_requires_model_review"):
        reviews["cross_section"], reviews["sections"] = {}, {}
    if reuse["literature_content"]:
        section_reviews = dict(reviews.get("sections") or {})
        for stage in ("blueprint", "introduction", "related_work", "discussion"):
            section_reviews.pop(stage, None)
        reviews["sections"] = section_reviews
    reviews.update({
        "schema_version": 1, "source_signature": signature,
        "authoring_signature": authoring_signature, "authoring_inputs": inputs,
        "authoring_options": options, "sections": dict(reviews.get("sections") or {}),
        "cross_section": dict(reviews.get("cross_section") or {}),
    })
    write_json(paths["reviews"], reviews)


def _copy_bibliography(paths: dict[str, Path]) -> None:
    source = paths["root"] / "literature" / "references.bib"
    if source.is_file():
        atomic_write_bytes(paths["paper"] / "references.bib", source.read_bytes())
