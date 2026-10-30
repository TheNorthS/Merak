"""Strict persistence for bounded cross-model review state."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Optional

from ..utils.atomic_write import atomic_write_json
from .review_models import ReviewRound, ReviewState


def load_review_state(
    project_path: str, *, run_id: str, max_rounds: int, evidence_mode: str
) -> Optional[ReviewState]:
    path = Path(project_path) / "review-stage" / "REVIEW_STATE.json"
    payload = _read_state_payload(path)
    if payload is None:
        return None
    stored_rounds = _stored_max_rounds(payload, path)
    if not _matches_run(payload, run_id, max_rounds, evidence_mode, stored_rounds):
        return None
    rounds = _restore_rounds(payload.get("rounds"), path)
    try:
        return ReviewState(
            run_id=str(payload.get("run_id") or run_id), rounds=rounds,
            current_round=int(payload.get("current_round") or 0),
            max_rounds=stored_rounds,
            final_score=float(payload.get("final_score") or 0),
            final_verdict=str(payload.get("final_verdict") or ""),
            is_complete=bool(payload.get("is_complete", False)),
            threshold_met=bool(payload.get("threshold_met", False)),
            bounded_complete=bool(payload.get("bounded_complete", False)),
            executor_provider=str(payload.get("executor_provider") or ""),
            reviewer_provider=str(payload.get("reviewer_provider") or ""),
            executor_model=str(payload.get("executor_model") or ""),
            reviewer_model=str(payload.get("reviewer_model") or ""),
            evidence_mode=str(payload.get("evidence_mode") or evidence_mode),
            publication_ready=bool(payload.get("publication_ready", False)),
            delivery_goal=str(payload.get("delivery_goal") or "submission_candidate"),
            review_policy_sha256=str(payload.get("review_policy_sha256") or ""),
            fallback_reason=str(payload.get("fallback_reason") or ""),
            owner_skill=str(payload.get("owner_skill") or "domain-review-loop"),
            policy_loaded=bool(payload.get("policy_loaded", False)),
            phase=str(payload.get("phase") or "pending"),
            source_bundle_sha256=str(payload.get("source_bundle_sha256") or ""),
            reviewer_session_ids=_string_list(payload, "reviewer_session_ids"),
            executor_session_ids=_string_list(payload, "executor_session_ids"),
            pdf_snapshots=[dict(value) for value in payload.get("pdf_snapshots") or []
                           if isinstance(value, dict)],
            transport_failure=dict(payload.get("transport_failure") or {})
            if isinstance(payload.get("transport_failure"), dict) else {},
        )
    except (TypeError, ValueError) as exc:
        raise RuntimeError(
            f"Managed review state contains invalid scalar fields: {path}"
        ) from exc


def _read_state_payload(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Managed review state is unreadable or corrupt: {path}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"Managed review state root must be a JSON object: {path}")
    return payload


def _stored_max_rounds(payload: dict[str, Any], path: Path) -> int:
    try:
        return int(payload.get("max_rounds") or 0)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(
            f"Managed review state has an invalid max_rounds value: {path}"
        ) from exc


def _matches_run(
    payload: dict[str, Any], run_id: str, max_rounds: int,
    evidence_mode: str, stored_rounds: int,
) -> bool:
    return bool(
        str(payload.get("managed_by") or "") == "cross_model_review_loop"
        and str(payload.get("run_id") or "") == str(run_id)
        and stored_rounds == int(max_rounds)
        and str(payload.get("evidence_mode") or "") == evidence_mode
    )


def _restore_rounds(raw_rounds: Any, path: Path) -> list[ReviewRound]:
    if not isinstance(raw_rounds or [], list):
        raise RuntimeError(f"Managed review state rounds must be a JSON array: {path}")
    rounds = []
    for index, item in enumerate(raw_rounds or []):
        if not isinstance(item, dict):
            raise RuntimeError(
                f"Managed review state contains a non-object round at index {index}: {path}"
            )
        try:
            rounds.append(ReviewRound(
                round_number=int(item.get("round") or 0),
                score=float(item.get("score") or 0),
                verdict=str(item.get("verdict") or "needs_work"),
                strengths=_string_values(item.get("strengths")),
                weaknesses=_string_values(item.get("weaknesses")),
                action_items=_string_values(item.get("action_items")),
                draft_blockers=item.get("draft_blockers"),
                pdf_snapshot=str(item.get("pdf_snapshot") or ""),
                visual_review={str(key): str(value)
                               for key, value in dict(item.get("visual_review") or {}).items()},
            ))
        except (TypeError, ValueError) as exc:
            raise RuntimeError(
                f"Managed review state has an invalid round at index {index}: {path}"
            ) from exc
    return rounds


def _string_values(value: Any) -> list[str]:
    return [str(item) for item in value or []]


def _string_list(payload: dict[str, Any], key: str) -> list[str]:
    return [str(value) for value in payload.get(key) or []]


def save_review_state(
    state: ReviewState,
    project_path: str,
    *,
    source_bundle: Callable[[str], tuple[str, list[Path]]],
) -> None:
    output_dir = Path(project_path) / "review-stage"
    output_dir.mkdir(parents=True, exist_ok=True)
    current_hash, source_paths = source_bundle(project_path)
    source_hash = str(state.source_bundle_sha256 or current_hash)
    state.source_bundle_sha256 = source_hash
    root = Path(project_path).expanduser().resolve()
    payload = _state_payload(state, source_hash)
    payload["sources"] = [
        path.relative_to(root).as_posix() if path.is_relative_to(root) else path.as_posix()
        for path in source_paths
    ]
    atomic_write_json(output_dir / "REVIEW_STATE.json", payload, indent=2)


def _state_payload(state: ReviewState, source_hash: str) -> dict[str, Any]:
    return {
        "managed_by": "cross_model_review_loop",
        "run_id": state.run_id, "current_round": state.current_round,
        "max_rounds": state.max_rounds, "final_score": state.final_score,
        "final_verdict": state.final_verdict, "is_complete": state.is_complete,
        "threshold_met": state.threshold_met, "bounded_complete": state.bounded_complete,
        "executor_provider": state.executor_provider,
        "reviewer_provider": state.reviewer_provider,
        "executor_model": state.executor_model, "reviewer_model": state.reviewer_model,
        "evidence_mode": state.evidence_mode,
        "publication_ready": state.publication_ready,
        "delivery_goal": state.delivery_goal,
        "review_policy_sha256": state.review_policy_sha256,
        "fallback_reason": state.fallback_reason, "owner_skill": state.owner_skill,
        "policy_loaded": state.policy_loaded, "phase": state.phase,
        "reviewer_session_ids": state.reviewer_session_ids,
        "executor_session_ids": state.executor_session_ids,
        "pdf_snapshots": state.pdf_snapshots,
        "transport_failure": state.transport_failure,
        "source_bundle_sha256": source_hash,
        "rounds": [_round_payload(item) for item in state.rounds],
    }


def _round_payload(review: ReviewRound) -> dict[str, Any]:
    return {
        "round": review.round_number, "score": review.score,
        "verdict": review.verdict, "strengths": review.strengths,
        "weaknesses": review.weaknesses, "action_items": review.action_items,
        "pdf_snapshot": review.pdf_snapshot,
        "visual_review": review.visual_review,
        "draft_blockers": review.draft_blockers,
    }
