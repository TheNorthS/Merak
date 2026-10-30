"""Authoritative implementation readiness declarations; blockers cannot finalize."""
from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class ImplementationBlocker(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    id: str = Field(min_length=1)
    owner: Literal["data", "method", "training", "evaluation", "integration"]
    path: str = Field(min_length=1)
    description: str = Field(min_length=1)


class ImplementationReadiness(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)
    integration_readiness: Literal["ready", "blocked", "in_progress"] = "in_progress"
    integration_blockers: list[ImplementationBlocker] = Field(default_factory=list)


class ExecutionReadiness(BaseModel):
    """External scientific prerequisites remain blocking for actual execution."""
    model_config = ConfigDict(extra="ignore", strict=True)
    execution_readiness: Literal["ready", "blocked", "not_checked"] = "not_checked"
    execution_prerequisites: list[ImplementationBlocker] = Field(default_factory=list)


def readiness_instruction() -> str:
    return (
        "RUN_SPEC implementation readiness: integration_readiness is ready, blocked or in_progress; "
        "integration_blockers is a list of {id, owner: data|method|training|evaluation|integration, "
        "path: exact stage-owned project-relative file, description}. Any unresolved blocker prevents "
        "finalization. Report upstream blockers at their real owner; never claim implementation complete "
        "because a test merely asserts that the implementation is blocked. METHOD_CONTRACT.status and "
        "hashes belong to the runtime: preserve existing values. Integration writes evidence patches only."
        " integration_readiness=ready is the author's submission for independent validation, not a "
        "passing verdict or proof of executed tests. When the requested source/interface repairs are "
        "complete, close those specific blockers with source-bound rationale in integration_resolution "
        "and submit ready; the runtime will independently reject any remaining defects. Do not leave "
        "'waiting for the runtime gate' as an implementation blocker: the gate runs after this invocation "
        "returns. Keep authored-but-unexecuted test status in current_static_review. Preserve substantive "
        "unresolved defects; never close them merely to obtain a passing gate. Avoid unrelated new "
        "features or new scientific requirements while resolving the supplied findings."
        " Do not copy stale fingerprint notices, owner handoff scheduling, or pending runtime verdicts "
        "into integration_blockers: those are runtime coordination state. On continuation compare "
        "existing blocker assertions with the current owner handoffs; if the named owner is now "
        "accepted with current fingerprints, resolve that specific outdated coordination assertion "
        "with a rationale, while preserving any independently unresolved source defect."
        " Keep missing external datasets, acquisition approvals, split-manifest inputs and unregistered "
        "scientific thresholds in execution_prerequisites (same item schema) with execution_readiness="
        "blocked or not_checked. Those prerequisites are distinct from defects in implemented code. "
        "Only integration may reclassify an existing item with an explicit rationale retained in RUN_SPEC; "
        "never delete an unresolved prerequisite or fabricate data/thresholds to claim ready. "
        "Code that cannot validate or consume those inputs remains an integration blocker. "
        "Do not list platform authorization, pending preflight execution, pending pilot execution, "
        "or 'not executed during authoring' as external execution_prerequisites. Authorization and "
        "the preflight-to-scientific-command order belong to the runtime. When all external inputs "
        "are available and the implemented preflight is declared, submit execution_readiness=ready "
        "with an empty execution_prerequisites list; retain execution_status=not_executed. This "
        "author submission never grants authorization or skips the runtime preflight. "
        "A synthetic preview may proceed only after code gates pass, while scientific execution remains "
        "blocked until execution_readiness=ready and execution_prerequisites is empty."
    )
