from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from server.services.experiment_health import ExperimentHealthMonitor, HealthPolicy
from server.services.api_visual_reviewer import (
    ApiVisualReview,
    api_visual_reviewer,
)
from server.services.node_risk_audit import (
    NODE_RISK_CHECKLIST,
    PENDING_RE,
    SIMULATION_SCOPE_RE,
    UNCERTAINTY_RE,
    _has_unbounded_supported_claim,
    _placeholder_excerpt,
    node_risk_audit_service,
)
from server.services.remote_experiment_runtime import (
    ProjectSnapshot,
    RunManifestStore,
    RuntimeSpec,
    experiment_runtime,
)
from server.services.research_workflow_contract import NODE_CONTRACTS
from server.services.scientific_evidence import scientific_evidence_service
from server.services.simulation_policy import (
    SIMULATION_PLOT_FAMILIES,
    SIMULATION_RENDERER_VERSION,
)
from server.workflows.engine import WorkflowEngine
from server.workflows.review_audit import (
    AuditChain,
    AuditResult,
    CrossModelReviewer,
    ReviewRound,
    ReviewState,
    Verdict,
    build_review_fix_scope,
    proof_source_bundle,
)
from server.agent.engine import agent_engine


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _visual_review(pdf_path: str = "paper/main.pdf") -> dict[str, str]:
    return {
        "pdf_path": pdf_path,
        "figure_quality": "Rendered figures are legible.",
        "caption_alignment": "Figure and table captions align with their floats.",
        "page_layout": "No clipping, overlap, or orphan heading was observed.",
        "table_formatting": "Table alignment is consistent.",
        "visual_consistency": "Typography and visual encoding are consistent.",
    }


def _patch_direct_reviewer_routes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executor = SimpleNamespace(name="executor-api", model="writer")
    reviewer = SimpleNamespace(name="reviewer-api", model="reviewer")
    monkeypatch.setattr(
        "server.workflows.review_audit.model_router.get_provider_route",
        lambda _role: (
            "executor-api",
            executor,
            "executor-api/writer",
        ),
    )
    monkeypatch.setattr(
        "server.workflows.review_audit.model_router."
        "get_isolated_provider_route",
        lambda role: (
            "reviewer-api",
            reviewer,
            "reviewer-api/reviewer",
        ),
    )


def _api_review_result(
    root: Path,
    payload: dict,
    invocation: int,
) -> ApiVisualReview:
    response = dict(payload)
    response.setdefault("visual_review", _visual_review())
    trace = root / ".merak" / "test-reviewer" / f"review-{invocation}"
    trace.mkdir(parents=True, exist_ok=True)
    return ApiVisualReview(
        text=json.dumps(response),
        invocation_id=f"model-api:test-review-{invocation}",
        model_identity="reviewer-api/reviewer",
        provider_name="reviewer-api",
        trace_path=str(trace),
    )
