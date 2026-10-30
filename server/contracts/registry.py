"""Single current registry for load-bearing research integrations."""

from __future__ import annotations

from dataclasses import dataclass

from ..services.research_contract_versions import (
    METHOD_CONTRACT_SCHEMA,
    SELECTED_IDEA_SCHEMA,
)


@dataclass(frozen=True)
class ArtifactContract:
    path: str
    schema: int | None
    owner: str
    consumers: tuple[str, ...]
    validator: str


@dataclass(frozen=True)
class IntegrationContract:
    identity: str
    owner: str
    consumers: tuple[str, ...]
    parser: str
    verifier: str
    failure_policy: str


@dataclass(frozen=True)
class WorkflowArtifactContract:
    primary: str
    required: tuple[str, ...]


artifact_contract_registry = {
    "selected_idea": ArtifactContract(
        "ideas/SELECTED_IDEA.json", SELECTED_IDEA_SCHEMA, "novelty",
        ("exp-design", "figure", "narrative", "paper", "audit"),
        "selected-idea-v2",
    ),
    "method_contract": ArtifactContract(
        "experiments/METHOD_CONTRACT.json", METHOD_CONTRACT_SCHEMA, "exp-design",
        ("exp-run", "results", "figure", "narrative", "paper", "audit"),
        "method-contract-v2",
    ),
    "run_spec": ArtifactContract(
        "experiments/RUN_SPEC.json", 1, "exp-design",
        ("exp-run", "results", "figure", "paper", "audit"), "run-spec-v1",
    ),
    "implementation_blueprint": ArtifactContract(
        "experiments/IMPLEMENTATION_BLUEPRINT.json", 1, "exp-design",
        ("exp-design", "figure"), "implementation-blueprint-v1",
    ),
    "implementation_evidence_patch": ArtifactContract(
        "experiments/IMPLEMENTATION_EVIDENCE_PATCH.json", 1, "exp-design",
        ("exp-design",), "implementation-evidence-patch-v1",
    ),
    "implementation_build": ArtifactContract(
        "experiments/IMPLEMENTATION_BUILD.json", 1, "exp-design",
        ("exp-design", "exp-run"), "implementation-build-v1",
    ),
    "result_analysis_build": ArtifactContract(
        "experiments/results/ANALYSIS_BUILD.json", 1, "results",
        ("figure", "narrative", "paper", "audit"), "result-analysis-build-v1",
    ),
    "simulation_manifest": ArtifactContract(
        "experiments/results/simulated/SIMULATION_MANIFEST.json", 11, "results",
        ("figure", "paper", "audit"), "simulation-manifest-v11",
    ),
    "scientific_asset_plan": ArtifactContract(
        "figures/SCIENTIFIC_ASSET_PLAN.json", 2, "figure",
        ("figure", "paper", "review", "ppt"), "scientific-asset-plan-v2",
    ),
    "figure_specs": ArtifactContract(
        "figures/FIGURE_SPECS.json", 4, "figure",
        ("figure", "paper", "review"), "figure-specs-v4",
    ),
    "figure_manifest": ArtifactContract(
        "figures/FIGURE_MANIFEST.json", 1, "figure",
        ("paper", "review", "audit", "compile", "ppt"), "figure-manifest-v1",
    ),
    "table_manifest": ArtifactContract(
        "paper/tables/TABLE_MANIFEST.json", 3, "paper",
        ("review", "audit", "compile"), "table-manifest-v3",
    ),
    "paper_build": ArtifactContract(
        "paper/PAPER_BUILD.json", 1, "compile",
        ("review", "audit", "ppt"), "paper-build-v1",
    ),
    "review_state": ArtifactContract(
        "review-stage/REVIEW_STATE.json", None, "review",
        ("audit", "compile", "ppt"), "review-state-current",
    ),
    "audit_results": ArtifactContract(
        "audit-results/AUDIT_RESULTS.json", 5, "audit",
        ("compile", "ppt"), "audit-bundle-v5",
    ),
    "slide_build": ArtifactContract(
        "slides/SLIDE_BUILD.json", 1, "ppt", (), "slide-build-v1",
    ),
}


integration_contract_registry = {
    "python_entrypoint": IntegrationContract(
        "python-entrypoint-v1", "exp-design", ("exp-run", "audit"),
        "server.contracts.entrypoints.parse_python_entrypoint",
        "PythonEntrypointRef.validation_issues", "route_to_owner",
    ),
}


workflow_artifact_contracts = {
    "lit": WorkflowArtifactContract(
        "literature/survey.md",
        ("literature/survey.md", "literature/references.bib"),
    ),
    "idea": WorkflowArtifactContract("ideas/ideas.md", ("ideas/ideas.md",)),
    "novelty": WorkflowArtifactContract(
        "ideas/novelty_report.md",
        ("ideas/novelty_report.md", "ideas/SELECTED_IDEA.json"),
    ),
    "exp-design": WorkflowArtifactContract(
        "experiments/EXPERIMENT_PLAN.md",
        (
            "experiments/EXPERIMENT_PLAN.md",
            "experiments/METHOD_CONTRACT.json",
            "experiments/RUN_SPEC.json",
            "experiments/IMPLEMENTATION_BLUEPRINT.json",
            "experiments/IMPLEMENTATION_EVIDENCE_PATCH.json",
            "experiments/src",
            "experiments/configs",
        ),
    ),
    "exp-run": WorkflowArtifactContract(
        "experiments/results", ("experiments/results",),
    ),
    "results": WorkflowArtifactContract(
        "experiments/results/analysis.md",
        ("experiments/results/analysis.md",),
    ),
    "figure": WorkflowArtifactContract(
        "figures/FIGURE_MANIFEST.json",
        (
            "figures/SCIENTIFIC_ASSET_PLAN.json",
            "figures/FIGURE_SPECS.json",
            "figures/FIGURE_MANIFEST.json",
        ),
    ),
    "narrative": WorkflowArtifactContract(
        "NARRATIVE_REPORT.md", ("NARRATIVE_REPORT.md", "paper/PAPER_PLAN.md"),
    ),
    "paper": WorkflowArtifactContract(
        "paper/main.tex",
        (
            "paper/main.tex", "paper/sections", "paper/PAPER_STYLE_PROFILE.json",
            "paper/CONTRIBUTION_BLUEPRINT.md", "paper/SECTION_CONTRACTS.json",
            "paper/SECTION_REVIEWS.json", "paper/DRAFT_STATE.json",
            "paper/CROSS_SECTION_REVIEW.md", "paper/tables/TABLE_MANIFEST.json",
        ),
    ),
    "review": WorkflowArtifactContract(
        "review-stage/REVIEW_STATE.json", ("review-stage/REVIEW_STATE.json",),
    ),
    "audit": WorkflowArtifactContract(
        "audit-results/AUDIT_RESULTS.json",
        (
            "audit-results/AUDIT_RESULTS.json",
            "audit-results/AUDIT_BUILD.json",
            "paper/PROOF_AUDIT.json",
        ),
    ),
    "compile": WorkflowArtifactContract(
        "paper/main.pdf", ("paper/main.pdf", "paper/PAPER_BUILD.json"),
    ),
    "ppt": WorkflowArtifactContract(
        "slides/main.pdf",
        ("slides/main.tex", "slides/main.pdf", "slides/SLIDE_BUILD.json",
         "slides/SLIDE_OUTLINE.md", "slides/speaker_notes.md", "slides/TALK_SCRIPT.md"),
    ),
}
