"""Profile-driven catalog of bounded research specialist subnodes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SpecialistSpec:
    id: str
    node_id: str
    name: str
    skill: str
    artifact: str
    purpose: str
    required_headings: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "node_id": self.node_id, "name": self.name,
            "skill": self.skill, "artifact": self.artifact,
            "purpose": self.purpose,
            "required_headings": list(self.required_headings),
            "execution_kind": "model_owned", "required": True,
        }


def selected_specialists(family: str, archetype: str) -> list[SpecialistSpec]:
    specs = [
        SpecialistSpec("domain-methodology", "exp-design", "领域方法学契约", "domain-methodology", "experiments/specialists/DOMAIN_METHODOLOGY.md", "Translate the accepted idea into discipline-specific study methodology.", ("# Domain Methodology Contract", "## Study Question and Units", "## Falsification and Decision Rules")),
        SpecialistSpec("domain-validation", "results", "领域验证规划与审计", "domain-validation", "experiments/specialists/DOMAIN_VALIDATION.md", "Require validation that distinguishes the claim from domain alternatives.", ("# Domain Validation Plan and Audit", "## Alternative Explanations", "## Evidence Status")),
    ]
    if archetype != "formal_theory":
        specs.append(SpecialistSpec("data-quality-audit", "exp-design", "数据质量与来源审计", "data-quality-audit", "experiments/specialists/DATA_QUALITY_AUDIT.md", "Audit provenance, independence, leakage, exclusions, and domain QC.", ("# Data Quality and Provenance Audit", "## Independence and Leakage", "## Blockers and Required Evidence")))
    if archetype not in {"formal_theory", "qualitative_mixed"}:
        specs.append(SpecialistSpec("statistical-analysis-plan", "exp-design", "统计分析计划", "statistical-analysis-plan", "experiments/specialists/STATISTICAL_ANALYSIS_PLAN.md", "Predeclare estimands, analysis units, uncertainty, and decision rules.", ("# Statistical Analysis Plan", "## Estimands and Endpoints", "## Decision and Reporting Rules")))
    if family in {"clinical_biomedical", "computational_biology", "social_behavioral", "qualitative_humanities"} or archetype in {"intervention_trial", "diagnostic_prognostic", "observational_cohort", "omics_discovery", "qualitative_mixed"}:
        specs.append(SpecialistSpec("ethics-governance", "exp-design", "伦理与治理审查", "ethics-governance", "experiments/specialists/ETHICS_GOVERNANCE.md", "Identify approvals, consent, privacy, safety, and disclosure blockers.", ("# Ethics and Governance Assessment", "## Execution Blockers", "## Required Manuscript Disclosures")))
    if family == "machine_learning" or archetype == "algorithm_benchmark":
        specs.append(SpecialistSpec("ablation-planner", "exp-design", "机制消融规划", "ablation-planner", "experiments/specialists/ABLATION_PLAN.md", "Bind ablations and matched controls to mechanisms and claims.", ("ablation", "control")))
    elif family in {"computer_systems", "engineering_systems"} or archetype == "systems_testbed":
        specs.append(SpecialistSpec("system-profile", "exp-design", "系统与测试床剖析", "system-profile", "experiments/specialists/SYSTEM_PROFILE.md", "Freeze hardware, software, workload, scale, failure, and cost conditions.", ("system", "workload")))
    elif family == "theoretical_formal" or archetype == "formal_theory":
        specs.append(SpecialistSpec("proof-writer", "exp-design", "证明义务规划", "proof-writer", "paper/proofs/PROOF_PLAN.md", "Define assumptions, theorem dependencies, proof obligations, and counterexamples.", ("proof", "assumption")))
    return sorted(specs, key=lambda item: (item.node_id, item.id))
