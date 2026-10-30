"""Persist an unchanged author's pending cross-section review across interruptions."""

from typing import Any

from .manuscript_text import read_owned_state, write_json


def _identity(paths: dict, state: dict, stage: str) -> dict[str, Any]:
    from .paper_drafting import AUTHOR_STAGE_ORDER, SECTION_BY_ID
    from .paper_draft_stages import stage_input_signature

    record = state.get("stages", {}).get(stage, {})
    return {"schema": 1, "authoring_signature": state.get("authoring_signature"),
            "scientific_freeze_id": state.get("scientific_freeze_id"),
            "output_hashes": dict(record.get("output_hashes") or {}),
            "input_signature": stage_input_signature(paths, stage, author_order=AUTHOR_STAGE_ORDER, section_by_id=SECTION_BY_ID)}


def record_deferred_rebind(paths: dict, stage: str) -> None:
    """Record only an already reviewed unchanged author; this never grants acceptance."""
    state = read_owned_state(paths["state"])
    state["stages"][stage]["deferred_input_rebind"] = _identity(paths, state, stage)
    write_json(paths["state"], state)


def deferred_rebind_current(paths: dict, state: dict, stage: str) -> bool:
    from .paper_drafting import AUTHOR_STAGE_ORDER, SECTION_BY_ID, paper_drafting_service
    from .paper_draft_stages import stage_outputs, stage_outputs_match

    if stage not in AUTHOR_STAGE_ORDER or stage == "consistency":
        return False
    record = state.get("stages", {}).get(stage, {})
    return bool(record.get("review_passed") and record.get("deferred_input_rebind") == _identity(paths, state, stage)
        and stage_outputs_match(stage_outputs(paths, stage, SECTION_BY_ID), record,
                                paper_drafting_service.stage_contract_version(stage), stage))
