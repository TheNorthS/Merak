"""Stage-aware skill orchestration for research workflow agents.

The registry may contain dozens of skills. Loading every skill into every model
call creates conflicting instructions and very large prompts, so each stage gets
one owner, a small specialist policy bundle, and independent validators.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from .skill_registry import SkillRegistry, skill_registry
from .skill_execution_trace import (
    SkillExecutionTrace,
    execution_summary,
    stage_execution_evidence,
    verified_model_invocation,
)
from .node_execution_contract import (
    NodeExecutionContract as NodeExecutionContract,
    resolve_execution_contract,
)
from .skill_selection import (
    apply_execution_mode,
    apply_family_specialists,
    apply_feature_specialists,
    apply_venue_and_assurance,
    figure_owner,
    implementation_family,
)


PHASE_SKILL_BUNDLES: dict[str, dict[str, list[str] | str]] = {
    "lit": {
        "primary": "research-lit",
        "specialists": ["comm-lit-review", "arxiv", "semantic-scholar", "openalex"],
        "validators": ["citation-audit"],
    },
    "idea": {
        "primary": "domain-idea-discovery",
        "specialists": ["idea-creator", "research-refine", "formula-derivation"],
        "validators": ["novelty-check", "research-review"],
    },
    "novelty": {
        "primary": "domain-novelty-check",
        "specialists": ["prior-art-search", "comm-lit-review", "openalex"],
        "validators": ["research-review"],
    },
    "exp-design": {
        "primary": "domain-experiment-plan",
        "specialists": ["ablation-planner", "training-check", "formula-derivation"],
        "validators": ["experiment-audit", "result-to-claim"],
    },
    "exp-run": {
        "primary": "experiment-bridge",
        "specialists": ["run-experiment", "experiment-queue", "monitor-experiment", "training-check"],
        "validators": ["experiment-audit"],
    },
    "results": {
        "primary": "domain-results-analysis",
        "specialists": ["result-to-claim", "ablation-planner", "paper-figure"],
        "validators": ["paper-claim-audit", "research-review"],
    },
    "figure": {
        "primary": "paper-figure",
        "specialists": [
            "model-svg-figure",
            "rich-svg-figure",
            "excalidraw-skill",
            "figure-spec",
            "mermaid-diagram",
            "paper-illustration",
        ],
        "validators": ["paper-claim-audit"],
    },
    "narrative": {
        "primary": "domain-narrative",
        "specialists": ["result-to-claim", "paper-plan", "research-wiki"],
        "validators": ["research-review"],
    },
    "paper": {
        "primary": "domain-paper-write",
        "specialists": ["figure-description"],
        "validators": ["paper-claim-audit", "citation-audit"],
    },
    "review": {
        "primary": "domain-review-loop",
        "specialists": ["research-review", "kill-argument", "paper-claim-audit"],
        "validators": ["citation-audit", "proof-checker"],
    },
    "audit": {
        "primary": "experiment-audit",
        "specialists": ["result-to-claim", "paper-claim-audit", "citation-audit", "kill-argument"],
        "validators": ["proof-checker"],
    },
    "compile": {
        "primary": "paper-compile",
        "specialists": ["citation-audit", "proof-checker"],
        "validators": [],
    },
    "ppt": {
        "primary": "paper-talk",
        "specialists": ["paper-slides", "slides-polish", "figure-description"],
        "validators": ["research-review"],
    },
}


@dataclass
class SkillPlan:
    node_id: str
    primary: str
    specialists: list[str] = field(default_factory=list)
    validators: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    registry_total: int = 0
    execution_kind: str = "model_owned"
    runtime_service: str = ""
    policy_required: bool = True
    model_execution_mode: str = "primary"
    execution_contract_issues: list[str] = field(default_factory=list)

    @property
    def selected(self) -> list[str]:
        return list(dict.fromkeys([self.primary, *self.specialists, *self.validators]))

    def as_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "primary": self.primary,
            "specialists": self.specialists,
            "validators": self.validators,
            "selected": self.selected,
            "reasons": self.reasons,
            "registry_total": self.registry_total,
            "execution_kind": self.execution_kind,
            "runtime_service": self.runtime_service,
            "policy_required": self.policy_required,
            "model_execution_mode": self.model_execution_mode,
            "execution_contract_issues": self.execution_contract_issues,
        }


class SkillOrchestrator:
    """Select executable skill owners and trace isolated invocations."""

    def __init__(self, registry: SkillRegistry = skill_registry):
        self.registry = registry
        self.execution_trace = SkillExecutionTrace(registry)

    @staticmethod
    def _dedupe_available(names: Iterable[str], available: set[str]) -> list[str]:
        return [name for name in dict.fromkeys(names) if name in available]

    def select(
        self,
        node_id: str,
        primary_hint: str,
        project_path: str,
        options: dict[str, Any] | None = None,
    ) -> SkillPlan:
        options = dict(options or {})
        bundle = PHASE_SKILL_BUNDLES.get(node_id, {})
        execution_contract = resolve_execution_contract(node_id, options, project_path=project_path)
        available = {item.id for item in self.registry.list_all()}
        primary = str(bundle.get("primary") or primary_hint.lstrip("/"))
        if primary not in available and primary_hint.lstrip("/") in available:
            primary = primary_hint.lstrip("/")

        specialists = list(bundle.get("specialists") or [])
        validators = list(bundle.get("validators") or [])
        reasons = [f"phase={node_id}"]

        family = implementation_family(project_path, options)
        specialists = apply_family_specialists(
            node_id, family, specialists, reasons,
        )
        specialists = apply_feature_specialists(
            node_id, specialists, reasons, options,
        )
        specialists = apply_execution_mode(
            node_id, family, specialists, reasons, options,
        )
        primary = figure_owner(
            node_id, primary, available, reasons, options, project_path=project_path,
        )
        apply_venue_and_assurance(
            node_id, specialists, validators, reasons, options,
        )

        disabled = {str(item).lstrip("/") for item in options.get("disabled_skills", []) if item}
        requested = [str(item).lstrip("/") for item in options.get("enabled_skills", []) if item]
        specialists.extend(requested)
        specialists = [item for item in specialists if item not in disabled and item != primary]
        validators = [item for item in validators if item not in disabled and item != primary]

        if available:
            specialists = self._dedupe_available(specialists, available)[:4]
            validators = self._dedupe_available(validators, available)[:3]
        else:
            specialists = list(dict.fromkeys(specialists))[:4]
            validators = list(dict.fromkeys(validators))[:3]

        return SkillPlan(
            node_id=node_id,
            primary=primary,
            specialists=specialists,
            validators=validators,
            reasons=reasons,
            registry_total=len(available),
            execution_kind=execution_contract.kind,
            runtime_service=execution_contract.runtime_service,
            policy_required=execution_contract.policy_required,
            model_execution_mode=execution_contract.model_execution_mode,
            execution_contract_issues=list(execution_contract.blocking_issues),
        )

    def full_policy(self, skill_name: str) -> str:
        """Load one complete SKILL.md for an actual isolated invocation."""
        metadata = self.registry.get_skill(skill_name.lstrip("/"))
        if not metadata or not metadata.file_path:
            return ""
        try:
            source_path = Path(metadata.file_path).resolve()
            policy = source_path.read_text(
                encoding="utf-8",
                errors="replace",
            ).strip()
            from .artifact_contract import validate_skill_artifact_contract_content

            validate_skill_artifact_contract_content(policy)
            return self._resolve_shared_reference_paths(policy, source_path)
        except OSError:
            return ""

    @staticmethod
    def _resolve_shared_reference_paths(policy: str, source_path: Path) -> str:
        """Resolve shared skill documents before policy text reaches an agent.

        Agent file tools resolve relative paths against the research project,
        while SKILL.md links are relative to the skill installation. Leaving
        links such as ``../shared-references/foo.md`` untouched therefore makes
        the agent search for a nonexistent project-local directory.
        """
        pattern = re.compile(
            r"(?P<path>(?:\.\./)+shared-references/[A-Za-z0-9._/-]+)"
        )

        def replace(match: re.Match[str]) -> str:
            raw_path = match.group("path")
            candidate = (source_path.parent / Path(raw_path)).resolve()
            return str(candidate) if candidate.is_file() else raw_path

        return pattern.sub(replace, policy)

    def readonly_reference_roots(self, skill_name: str) -> list[str]:
        """Return verified read-only roots belonging to one registered skill."""
        metadata = self.registry.get_skill(skill_name.lstrip("/"))
        if not metadata or not metadata.file_path:
            return []
        try:
            source_path = Path(metadata.file_path).resolve()
            shared_root = (source_path.parent.parent / "shared-references").resolve()
        except OSError:
            return []
        return [str(shared_root)] if shared_root.is_dir() else []

    def render_owner(self, plan: SkillPlan) -> str:
        """Render only the stage owner's full skill; delegates stay unloaded."""
        if not plan.policy_required:
            return ""
        policy = self.full_policy(plan.primary)
        if not policy:
            return ""
        return (
            "## Loaded MERAK Skill Invocation\n"
            f"Invocation role: stage owner\nSkill: `/{plan.primary}`\n"
            "The complete SKILL.md below is the executable operating contract for this "
            "session. Follow it directly. Do not pretend that another skill ran merely "
            "because its name appears in context. Use the `Skill` tool when a concrete "
            "delegate is required; that tool creates a separate session with the delegate's "
            "complete SKILL.md.\n\n"
            + policy
        )

    def render_context(self, plan: SkillPlan) -> str:
        validators = ", ".join(plan.validators) or "deterministic artifact/evidence gates"
        specialists = ", ".join(plan.specialists) or "none"
        sections = [
            "## Skill Invocation Routing",
            f"Executed stage owner: `/{plan.primary}`.",
            f"Available on-demand delegates (not loaded yet): {specialists}.",
            f"Independent validators reserved for their validation stage: {validators}.",
            "A delegate counts as applied only after a successful `Skill` tool call. "
            "Do not copy delegate instructions into this prompt and do not report an "
            "uninvoked delegate as completed.",
            (
                "For the figure stage, invoke each specialist required by "
                "`recommended_skill` at most once and group that backend's assets into "
                "the same invocation. For other stages, invoke at most two delegates. "
                "Only delegate concrete work with a distinct output; nested delegates "
                "cannot invoke further skills."
                if plan.node_id == "figure"
                else
                "Invoke at most two delegates, only for concrete work with a distinct "
                "output. Nested delegates cannot invoke further skills."
            ),
            "Before writing, make a short internal claim -> evidence -> action plan. Preserve the user's research objective and explicitly mark unsupported claims.",
        ]
        return "\n\n".join(sections)

    _verified_model_invocation = staticmethod(verified_model_invocation)
    _stage_execution_evidence = staticmethod(stage_execution_evidence)

    def execution_gate(
        self,
        project_path: str,
        run_id: str,
        node_id: str,
    ) -> dict[str, Any]:
        """Verify that this run used the execution owner declared for a stage."""
        return self.execution_trace.execution_gate(project_path, run_id, node_id)

    def workflow_execution_gate(
        self,
        project_path: str,
        run_id: str,
        node_ids: Iterable[str],
    ) -> dict[str, Any]:
        """Aggregate truthful execution ownership across workflow stages."""
        return self.execution_trace.workflow_execution_gate(
            project_path, run_id, node_ids,
        )

    _execution_summary = staticmethod(execution_summary)

    def record(self, project_path: str, run_id: str, plan: SkillPlan) -> Path:
        return self.execution_trace.record(project_path, run_id, plan)

    def mark_execution(
        self,
        project_path: str,
        run_id: str,
        node_id: str,
        skill_name: str,
        status: str,
        *,
        role: str = "primary",
        session_id: str = "",
        output: str = "",
        error: str = "",
        policy_loaded: bool | None = None,
        execution_kind: str = "model_owned",
        model_provider: str = "",
        model_name: str = "",
        completion_mode: str = "",
    ) -> Path:
        """Persist actual skill lifecycle state instead of prompt-application claims."""
        return self.execution_trace.mark_execution(
            project_path,
            run_id,
            node_id,
            skill_name,
            status,
            role=role,
            session_id=session_id,
            output=output,
            error=error,
            policy_loaded=policy_loaded,
            execution_kind=execution_kind,
            model_provider=model_provider,
            model_name=model_name,
            completion_mode=completion_mode,
        )

    def mark_runtime_execution(
        self,
        project_path: str,
        run_id: str,
        node_id: str,
        runtime_service: str,
        status: str,
        *,
        operation_id: str = "",
        output: str = "",
        error: str = "",
    ) -> Path:
        """Persist runtime work separately from model skill execution."""
        return self.execution_trace.mark_runtime_execution(
            project_path,
            run_id,
            node_id,
            runtime_service,
            status,
            operation_id=operation_id,
            output=output,
            error=error,
        )


skill_orchestrator = SkillOrchestrator()
