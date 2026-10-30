"""Build review acceptance facts from durable structured rounds, never prose scores."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from ..utils.atomic_write import atomic_write_json


class ReviewAcceptanceHost(Protocol):
    def _review_layout_revision_findings(
        self, project_path: str, state: dict[str, Any]
    ) -> list[dict[str, Any]]: ...
    def _revision_target_files(self, *values: Any) -> list[str]: ...
    def _review_visual_evidence_gate(
        self, project_path: str, state: dict[str, Any], rounds: list[dict[str, Any]]
    ) -> dict[str, Any]: ...
    def _verdict_id(self, node_id: str, artifacts: list[Path]) -> str: ...


@dataclass
class ReviewAcceptanceContext:
    project_path: str
    state_path: Path
    paper_path: Path
    state: dict[str, Any]
    reviewer: str
    state_error: str = ""
    rounds: list[dict[str, Any]] = field(default_factory=list)
    layout_findings: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class ReviewOutcome:
    score: float
    verdict: str
    semantic_threshold_met: bool
    visual_evidence: dict[str, Any]
    threshold_met: bool
    bounded_complete: bool
    active_layout_findings: list[dict[str, Any]]

    @property
    def source(self) -> str:
        return "review-state"


def load_acceptance_context(project_path: str) -> ReviewAcceptanceContext:
    state_path = Path(project_path) / "review-stage" / "REVIEW_STATE.json"
    state: dict[str, Any] = {}
    error = ""
    if state_path.exists():
        try:
            value = json.loads(state_path.read_text(encoding="utf-8-sig"))
            if not isinstance(value, dict):
                raise ValueError("REVIEW_STATE root must be an object")
            state = value
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as failure:
            error = str(failure)
    rounds = state.get("rounds") or []
    if not isinstance(rounds, list):
        error = "REVIEW_STATE rounds must be an array"
        rounds = []
    return ReviewAcceptanceContext(
        project_path,
        state_path,
        Path(project_path) / "paper" / "main.tex",
        state,
        str(state.get("reviewer_model") or "cross-model:reviewer"),
        error,
        [item for item in rounds if isinstance(item, dict)],
    )


def _score_and_verdict(context: ReviewAcceptanceContext) -> tuple[float, str]:
    last_round = context.rounds[-1]
    score = context.state.get("final_score")
    if score is None:
        score = last_round.get("score")
    verdict = str(context.state.get("final_verdict") or last_round.get("verdict") or "")
    try:
        numeric = float(score)
    except (TypeError, ValueError):
        numeric = 0.0
    if not math.isfinite(numeric) or numeric < 0 or numeric > 10:
        numeric = 0.0
    return numeric, verdict.lower().replace("-", "_").replace(" ", "_")


def _bounded_complete(context: ReviewAcceptanceContext, threshold_met: bool) -> bool:
    try:
        current = int(context.state.get("current_round") or len(context.rounds))
    except (TypeError, ValueError):
        current = len(context.rounds)
    try:
        maximum = int(context.state.get("max_rounds") or 0)
    except (TypeError, ValueError):
        maximum = 0
    return bool(
        context.state.get("bounded_complete")
        or threshold_met
        or context.state.get("is_complete")
        or (maximum > 0 and current >= maximum and len(context.rounds) >= maximum)
    )


def review_outcome(
    host: ReviewAcceptanceHost, context: ReviewAcceptanceContext
) -> ReviewOutcome:
    score, verdict = _score_and_verdict(context)
    semantic_met = score >= 6 and verdict in {"ready", "almost"}
    managed = context.state.get("managed_by") == "cross_model_review_loop"
    visual = host._review_visual_evidence_gate(
        context.project_path, context.state, context.rounds
    )
    reconciliation = context.state.get("paper_reconciliation")
    reconciliation_failed = isinstance(reconciliation, dict) and not reconciliation.get(
        "passed"
    )
    active = (
        []
        if visual.get("verified") is True or reconciliation_failed
        else context.layout_findings
    )
    threshold_met = semantic_met and (not managed or visual.get("verified") is True)
    return ReviewOutcome(
        score,
        verdict,
        semantic_met,
        visual,
        threshold_met,
        _bounded_complete(context, threshold_met),
        active,
    )


def persist_derived_outcome(
    context: ReviewAcceptanceContext, outcome: ReviewOutcome
) -> None:
    updated = {
        **context.state,
        "threshold_met": outcome.threshold_met,
        "bounded_complete": outcome.bounded_complete,
        "is_complete": outcome.bounded_complete,
    }
    if context.state.get("delivery_goal") == "reviewable_draft":
        updated["publication_ready"] = False
    if updated == context.state:
        return
    try:
        atomic_write_json(context.state_path, updated)
    except OSError as error:
        context.state_error = str(error)
        return
    context.state = updated
