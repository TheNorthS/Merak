"""Paths, signatures, and durable state for staged paper drafting."""

from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path
from typing import Any, Iterable, Optional

from .manuscript_text import (
    read_json,
    read_owned_state,
    read_text,
    stable_source_hash,
    word_count,
    write_json,
)
from .workflow_user_constraints import USER_CONSTRAINTS_PROMPT_VERSION, node_input_constraints

FIGURE_SCOPE_PROMPT_VERSION = 1

AUTHORING_SOURCE_PATHS = (
    "literature/survey.md",
    "literature/references.bib",
    "ideas/SELECTED_IDEA.json",
    "experiments/METHOD_CONTRACT.json",
    "experiments/EXPERIMENT_PLAN.md",
    "experiments/RUN_SPEC.json",
    "experiments/configs/main.yaml",
    "experiments/src/models.py",
    "experiments/src/objectives.py",
    "experiments/results/analysis.md",
    "NARRATIVE_REPORT.md",
    "paper/PAPER_PLAN.md",
)
DERIVED_SOURCE_PATHS = (
    "figures/SCIENTIFIC_ASSET_PLAN.json",
    "figures/FIGURE_MANIFEST.json",
    "paper/tables/TABLE_MANIFEST.json",
)


def directed_issue_signature(issues: Iterable[str]) -> str:
    normalized = sorted({
        re.sub(
            r"\b\d+(?:\.\d+)?\b",
            "<number>",
            " ".join(str(item or "").casefold().split()),
        )
        for item in issues
        if str(item or "").strip()
    })
    if not normalized:
        return ""
    return hashlib.sha256(
        json.dumps(normalized, ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def record_directed_attempt(
    paths: dict[str, Path],
    stage_id: str,
    issue_signature: str,
    attempts: int,
    artifact_signature: str = "",
) -> None:
    state = read_owned_state(paths["state"])
    record = dict(state.setdefault("stages", {}).get(stage_id) or {})
    record["directed_issue_signature"] = issue_signature
    record["directed_attempts"] = max(0, int(attempts))
    if artifact_signature:
        record["directed_artifact_signature"] = artifact_signature
    record["directed_updated_at"] = time.time()
    state["stages"][stage_id] = record
    state["updated_at"] = time.time()
    write_json(paths["state"], state)


def drafting_paths(project_path: str | Path) -> dict[str, Path]:
    root = Path(project_path).expanduser().resolve()
    paper = root / "paper"
    return {
        "root": root, "paper": paper, "sections": paper / "sections",
        "main": paper / "main.tex", "title": paper / "TITLE.txt",
        "blueprint": paper / "CONTRIBUTION_BLUEPRINT.md",
        "style": paper / "PAPER_STYLE_PROFILE.json",
        "profile": paper / "PAPER_PROFILE.json",
        "contracts": paper / "SECTION_CONTRACTS.json",
        "reviews": paper / "SECTION_REVIEWS.json",
        "state": paper / "DRAFT_STATE.json",
        "cross_review": paper / "CROSS_SECTION_REVIEW.md",
        "freeze": paper / "SCIENTIFIC_FREEZE.json",
        "authoring_assets": paper / "AUTHORING_ASSET_MANIFEST.json",
    }


def source_paths(root: Path) -> list[Path]:
    return [
        root / Path(relative)
        for relative in (*AUTHORING_SOURCE_PATHS, *DERIVED_SOURCE_PATHS)
    ]


def authoring_source_paths(root: Path) -> list[Path]:
    return [root / Path(relative) for relative in AUTHORING_SOURCE_PATHS]


def signature_options(options: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    raw = options or {}
    return {
        "target_venue": str(raw.get("target_venue") or ""),
        "venue_template_path": str(raw.get("venue_template_path") or ""),
        "target_pages": int(raw.get("target_pages") or 0),
        "research_mode": str(raw.get("research_mode") or ""),
        "research_family": str(raw.get("research_family") or "auto"),
        "study_archetype": str(raw.get("study_archetype") or "auto"),
        "run_experiment": raw.get("run_experiment") is True,
        "evidence_mode": str(
            raw.get("non_experiment_evidence_mode") or raw.get("evidence_mode") or ""
        ),
        "node_inputs": node_input_constraints(raw),
        "user_constraints_prompt_version": USER_CONSTRAINTS_PROMPT_VERSION,
        "figure_scope_prompt_version": FIGURE_SCOPE_PROMPT_VERSION,
    }


def gate_signature_options(
    options: Optional[dict[str, Any]], stored_options: Optional[dict[str, Any]]
) -> dict[str, Any]:
    resolved = signature_options(stored_options)
    supplied = options or {}
    for key in ("target_venue", "research_mode", "research_family", "study_archetype"):
        value = str(supplied.get(key) or "").strip()
        if value:
            resolved[key] = value
    if "venue_template_path" in supplied:
        resolved["venue_template_path"] = str(
            supplied.get("venue_template_path") or ""
        ).strip()
    target_pages = _positive_int(supplied.get("target_pages"))
    if target_pages:
        resolved["target_pages"] = target_pages
    if "run_experiment" in supplied and supplied.get("run_experiment") is not None:
        resolved["run_experiment"] = supplied["run_experiment"] is True
    mode = str(
        supplied.get("non_experiment_evidence_mode")
        or supplied.get("evidence_mode") or ""
    ).strip()
    if mode:
        resolved["evidence_mode"] = mode
    if "node_inputs" in supplied:
        resolved["node_inputs"] = node_input_constraints(supplied)
    return resolved


def _positive_int(value: Any) -> int:
    try:
        parsed = int(value or 0)
    except (TypeError, ValueError):
        return 0
    return parsed if parsed > 0 else 0


def authoring_input_hashes(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): stable_source_hash(path) or "<missing>"
        for path in authoring_source_paths(root)
    }


def evidence_status(root: Path) -> dict[str, Any]:
    plan = read_json(root / "figures" / "SCIENTIFIC_ASSET_PLAN.json")
    snapshot = read_json(root / "paper" / "EVIDENCE_SNAPSHOT.json")
    mode = str(plan.get("evidence_mode") or snapshot.get("evidence_mode") or "design_only")
    eligible = bool(plan.get("submission_eligible") or snapshot.get("submission_eligible"))
    if mode not in {"executed", "existing_results", "secondary_analysis"}:
        eligible = False
    return {
        "mode": mode,
        "submission_eligible": eligible,
        "experiments_pending": mode in {"design_only", "execution_pending"},
        "missing_requirements": [
            str(item) for item in plan.get("missing_requirements", [])
            if str(item).strip()
        ],
    }


def analyse_tex_source(path: Path) -> dict[str, Any]:
    files = [path] if path.is_file() else sorted(path.rglob("*.tex"))[:100]
    text = "\n".join(read_text(item) for item in files)
    return {
        "path": str(path),
        "tex_files": len(files),
        "words": word_count(text),
        "sections": [
            " ".join(re.sub(r"\\[A-Za-z]+", " ", value).split())
            for value in re.findall(r"\\section\*?\{([^}]+)\}", text)
        ][:30],
        "figures": len(re.findall(r"\\begin\{figure\*?\}", text)),
        "tables": len(re.findall(r"\\begin\{table\*?\}", text)),
    }
