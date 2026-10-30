"""Data contracts shared by independent review and audit workflows."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

NATIVE_VISUAL_REVIEW_TRANSPORTS = frozenset({
    "independent-model-api-native-vision-v1",
})


class Verdict(str, Enum):
    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    BLOCKED = "BLOCKED"
    ERROR = "ERROR"


class AuditSourceChangedError(RuntimeError):
    """Raised when audited inputs change before the bundle commit marker."""


@dataclass
class ReviewRound:
    """One independent manuscript review round."""

    round_number: int
    score: float
    verdict: str
    strengths: list[str] = field(default_factory=list)
    weaknesses: list[str] = field(default_factory=list)
    action_items: list[str] = field(default_factory=list)
    raw_review: str = ""
    pdf_snapshot: str = ""
    visual_review: dict[str, str] = field(default_factory=dict)
    debate_ruling: Optional[str] = None
    timestamp: float = field(default_factory=time.time)
    draft_blockers: list[str] | None = None

    def has_complete_visual_review(self) -> bool:
        required = {
            "pdf_path", "figure_quality", "caption_alignment", "page_layout",
            "table_formatting", "visual_consistency",
        }
        return bool(
            required.issubset(self.visual_review)
            and all(str(self.visual_review.get(key) or "").strip() for key in required)
            and self.visual_review.get("_coordinator_verified") == "true"
            and bool(self.visual_review.get("_source_bundle_sha256"))
            and bool(self.visual_review.get("_visual_bundle_sha256"))
            and bool(self.visual_review.get("_visual_content_sha256"))
            and bool(self.visual_review.get("_review_image_paths"))
            and bool(self.visual_review.get("_review_image_bundle_sha256"))
            and bool(self.visual_review.get("_review_response_sha256"))
            and self.visual_review.get("_review_transport")
            in NATIVE_VISUAL_REVIEW_TRANSPORTS
            and bool(self.visual_review.get("_review_trace_path"))
            and str(self.visual_review.get("_review_invocation_id") or "").startswith("model-api:")
            and str(self.visual_review.get("_review_model_identity") or "").strip()
        )


@dataclass
class ReviewState:
    """Durable state for a bounded cross-model review loop."""

    run_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    rounds: list[ReviewRound] = field(default_factory=list)
    current_round: int = 0
    max_rounds: int = 4
    final_score: float = 0
    final_verdict: str = ""
    is_complete: bool = False
    threshold_met: bool = False
    bounded_complete: bool = False
    executor_provider: str = ""
    reviewer_provider: str = ""
    executor_model: str = ""
    reviewer_model: str = ""
    evidence_mode: str = "executed"
    publication_ready: bool = False
    fallback_reason: str = ""
    owner_skill: str = "domain-review-loop"
    policy_loaded: bool = False
    phase: str = "pending"
    source_bundle_sha256: str = ""
    reviewer_session_ids: list[str] = field(default_factory=list)
    executor_session_ids: list[str] = field(default_factory=list)
    pdf_snapshots: list[dict[str, Any]] = field(default_factory=list)
    transport_failure: dict[str, Any] = field(default_factory=dict)
    delivery_goal: str = "submission_candidate"
    review_policy_sha256: str = ""

    def should_stop(self) -> bool:
        if not self.rounds:
            return False
        last = self.rounds[-1]
        return (
            last.score >= 6
            and last.verdict in ("ready", "almost")
            and last.has_complete_visual_review()
        )


@dataclass
class AuditResult:
    """Result for one deterministic/model audit layer."""

    layer: int
    layer_name: str
    verdict: Verdict
    summary: str
    details: Any = ""
    evidence: list[Any] = field(default_factory=list)
    method: str = "model"
    skill_name: str = ""
    session_id: str = ""
    policy_loaded: bool = False
    model_name: str = ""
    reason_code: str = ""
    audited_input_hashes: dict[str, str] = field(default_factory=dict)
    trace_path: str = ""
    timestamp: float = field(default_factory=time.time)
    delivery_goal: str = "submission_candidate"
    draft_blockers: list[str] | None = None
