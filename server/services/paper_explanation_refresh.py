"""Preserve prose after interpretation-only updates while requiring fresh model consistency."""

from pathlib import Path
from typing import Any

from .manuscript_text import read_owned_state


EXPLANATION_INPUTS = {"experiments/results/analysis.md", "NARRATIVE_REPORT.md", "paper/PAPER_PLAN.md"}


def can_reconcile_explanation_update(paths: dict[str, Path], previous: dict[str, Any],
                                     inputs: dict[str, str], options: dict[str, Any], schema: int) -> bool:
    """No new study, scientific assets, evidence, options or unsupported state may reuse this route."""
    from .paper_scientific_freeze import scientific_freeze_inputs

    before = previous.get("authoring_inputs") or {}
    changed = {key for key in set(before) | set(inputs) if before.get(key) != inputs.get(key)}
    if (previous.get("schema_version") != schema or not changed or not changed <= EXPLANATION_INPUTS
            or previous.get("authoring_options") != options or set(before) != set(inputs)
            or not _complete_candidate_inputs(paths, previous)):
        return False
    freeze = read_owned_state(paths["paper"] / "SCIENTIFIC_FREEZE.json")
    current = scientific_freeze_inputs(paths["root"])
    old = freeze.get("inputs") or {}
    return bool(freeze.get("schema_version") == 1 and old and old.keys() == current.keys()
        and all(old[key] == current[key] for key in current if key not in EXPLANATION_INPUTS))


def _complete_candidate_inputs(paths: dict[str, Path], state: dict[str, Any]) -> bool:
    """Pending directed edits may keep complete candidates, but absent prose cannot be reused."""
    from .paper_drafting import AUTHOR_STAGE_ORDER, SECTION_BY_ID
    from .paper_draft_stages import stage_outputs

    records = state.get("stages") or {}
    return all(stage in records and all(path.is_file() and path.stat().st_size > 0
        for path in stage_outputs(paths, stage, SECTION_BY_ID))
        for stage in AUTHOR_STAGE_ORDER if stage != "consistency")


def reset_explanation_reviews(state: dict[str, Any]) -> None:
    """Retain candidate prose; withdraw every review and require a new independent model report."""
    for stage, record in state["stages"].items():
        record["prior_source_attempts"] = record.get("attempts", 0)
        record.update(status="pending", attempts=0 if stage in {"consistency", "assembly"} else 1,
                      review_passed=False, review_issues=[])
        for key in ("validator_signature", "completed_at", "error", "directed_attempts", "deferred_input_rebind",
                    "reviewed_input_signature", "reviewed_report_sha256"):
            record.pop(key, None)
        if stage in {"consistency", "assembly"}:
            for key in ("output_hashes", "input_signature"):
                record.pop(key, None)
    state["explanation_refresh_requires_model_review"] = True
