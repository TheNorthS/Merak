"""Durable section-by-section manuscript drafting and acceptance."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable, Iterable, Optional

from .manuscript_text import (
    DISPLAY_MATH_RE as DISPLAY_MATH_RE,
    bib_keys as bib_keys,
    citation_keys as citation_keys,
    final_consistency_verdict as final_consistency_verdict,
    reference_keys as reference_keys,
    stable_source_hash as stable_source_hash,
    word_count as word_count,
)
from . import paper_draft_state
from .paper_draft_state_mixin import PaperDraftStateMixin
from .paper_venue_config import (
    CUSTOM_TEMPLATE_CONTENT_MARKERS,
    CUSTOM_TEMPLATE_DEPENDENCY_EXTENSIONS,
    CUSTOM_TEMPLATE_EXTENSIONS,
    CUSTOM_TEMPLATE_RESERVED_TARGETS,
    VENUE_FAMILY_BUNDLES,
    VENUE_TEMPLATE_BUNDLES,
)
from .paper_profile import EXEMPLAR_STATISTICS
from .simulation_policy import (
    SIMULATION_END_DISCLOSURE,
    SIMULATION_END_DISCLOSURE_TITLE,
)


DRAFT_SCHEMA_VERSION = 3
STYLE_PROFILE_SCHEMA_VERSION = 2
SECTION_CONTRACT_SCHEMA_VERSION = 8
CONSISTENCY_CONTRACT_VERSION = 5
ASSEMBLY_CONTRACT_VERSION = 6
SEMANTIC_DERIVED_HASH_MODE = "semantic-derived-v1"
StageInvoker = Callable[[str, str, str], Awaitable[str]]
EventEmitter = Callable[[str, dict[str, Any]], Awaitable[None]]


@dataclass(frozen=True)
class SectionSpec:
    id: str
    filename: str
    title: str
    minimum_words: int
    maximum_words: int
    minimum_citations: int
    purpose: str
    required_moves: tuple[str, ...]


class PaperDraftingError(RuntimeError):
    """A bounded stage failed its local scientific contract."""

    def __init__(self, stage_id: str, issues: Iterable[str]):
        self.stage_id = stage_id
        self.issues = [str(item) for item in issues if str(item).strip()]
        super().__init__(
            f"Staged paper drafting failed at {stage_id}: "
            + "; ".join(self.issues[:8])
        )


BUILTIN_EXEMPLARS = EXEMPLAR_STATISTICS

SECTION_SPECS = (
    SectionSpec("introduction", "01_introduction.tex", "Introduction", 600, 850, 7,
                "Move from problem value to a specific gap, mechanism rationale, and falsifiable contributions.",
                ("field value", "unresolved limitation", "closest-work insufficiency",
                 "mechanism rationale", "falsifiable contributions", "evidence-bounded scope")),
    SectionSpec("related_work", "02_related_work.tex", "Related Work", 600, 900, 14,
                "Synthesize prior work by method and assumption, then position this paper.",
                ("three methodological categories", "assumption-level comparison",
                 "closest-work positioning", "verified citations")),
    SectionSpec("method", "03_method.tex", "Method", 1000, 1500, 3,
                "Define notation, derive every accepted mechanism, objective, and reproducible procedure.",
                ("problem setup", "required mechanisms", "objective", "training/inference",
                 "implementation implications", "method figure interpretation")),
    SectionSpec("experiments", "04_experiments.tex", "Experimental Setup", 800, 1150, 5,
                "Freeze data, splits, preprocessing, baselines, metrics, compute, and leakage controls.",
                ("datasets and units", "leakage-safe splits", "matched baselines",
                 "metrics", "compute details", "uncertainty and statistics")),
    SectionSpec("results", "05_results.tex", "Results", 650, 1050, 2,
                "Answer registered questions with provenance-backed measurements, or planned analyses in protocol mode.",
                ("primary comparison", "ablations", "robustness", "failure analysis", "uncertainty")),
    SectionSpec("discussion", "06_discussion.tex", "Discussion", 350, 800, 2,
                "Interpret evidence, alternatives, generalization, and negative outcomes.",
                ("scientific interpretation", "alternative explanations", "closest work",
                 "negative-result interpretation", "scope")),
    SectionSpec("limitations", "07_limitations.tex", "Limitations", 180, 320, 0,
                "State evidence, data, compute, validity, and concrete mitigation limits.",
                ("evidence maturity", "data/split limits", "compute limits",
                 "external validity", "mitigation")),
    SectionSpec("conclusion", "08_conclusion.tex", "Conclusion", 150, 230, 0,
                "Answer the question at evidence-permitted strength and identify the decisive next test.",
                ("answer", "mechanism contribution", "calibrated conclusion", "next test")),
)
SECTION_BY_ID = {item.id: item for item in SECTION_SPECS}
AUTHOR_STAGE_ORDER = (
    "blueprint", "introduction", "related_work", "method", "experiments",
    "results", "discussion", "limitations", "conclusion", "front_matter", "consistency",
)
PAPER_STAGE_ORDER = (*AUTHOR_STAGE_ORDER, "assembly")
PAPER_STAGE_LABELS = {
    "blueprint": "Contribution blueprint",
    "introduction": "Introduction",
    "related_work": "Related Work",
    "method": "Method",
    "experiments": "Experimental Setup",
    "results": "Results or Evaluation Protocol",
    "discussion": "Discussion",
    "limitations": "Limitations",
    "conclusion": "Conclusion",
    "front_matter": "Title and Abstract",
    "consistency": "Cross-section consistency",
    "assembly": "Venue-aware manuscript assembly",
}

SUPERIORITY_RE = re.compile(
    r"\b(?:we (?:demonstrate|show|establish) that|our (?:method|model) "
    r"(?:outperforms|surpasses|achieves)|"
    r"(?:achiev(?:e|es|ed)|set(?:s)?|establish(?:es|ed)?) "
    r"(?:a |the )?state[- ]of[- ]the[- ]art|"
    r"state[- ]of[- ]the[- ]art (?:performance|results?|accuracy|f1|auroc)|"
    r"significantly (?:improves|outperforms)|improves? (?:accuracy|f1|auroc) by)\b",
    re.IGNORECASE,
)
ADMIN_RE = re.compile(
    r"(?i:publication[_\ ]ready|claim[- ]to[- ]evidence|artifact status|"
    r"workflow (?:gate|status))|\bNOT EVIDENCE\b",
    re.MULTILINE,
)
AI_ISM_RE = re.compile(
    r"\b(?:delve|pivotal|tapestry|multifaceted landscape|it is worth noting|"
    r"it is important to note|in order to)\b",
    re.IGNORECASE,
)
ALTERNATIVE_EXPLANATION_RE = re.compile(
    r"\b(?:alternative|rival|competing|plausible|several|multiple) explanations?\b|"
    r"\b(?:confound(?:er|ing)?|cannot rule out|could instead)\b",
    re.IGNORECASE,
)
NEGATIVE_RESULT_RE = re.compile(
    r"\b(?:negative|null) (?:result|outcome|finding|evidence)s?\b|"
    r"\bnull (?:[a-z]+(?:[- ][a-z]+)? ){0,2}(?:interaction|effect|difference|estimate)s?\b"
    r"[^.]{0,180}\b(?:mean|indicat|suggest|imply|show|support|detect)\w*\b|"
    r"\bnegative transfer\b[^.]{0,180}\b(?:failure|claim|interpret|report|imply|suggest)\w*\b|"
    r"\b(?:estimate|interaction|effect|contrast)\b[^.]{0,50}\b(?:near zero|is null|null, reversed)\b"
    r"[^.]{0,220}\b(?:weaken|unsupported|conclusion|support|mean|counterevidence)\w*\b|"
    r"\bintervals? (?:spanning|crossing|including) zero\b[^.]{0,100}"
    r"\b(?:does not|cannot|insufficient|inconclusive)\b|"
    r"\b(?:adverse|unfavourable|unfavorable) (?:primary )?(?:ordering|results?|findings?)\b|"
    r"\bdoes not support\b[^.]{0,100}\b(?:positive|benefit|improvement|gain)\b|"
    r"\b(?:failure to|no (?:benefit|difference|improvement|effect)|no support for)\b|"
    r"\b(?:absence|lack) of (?:a |any )?(?:qualifying |registered )?"
    r"(?:effect|difference|improvement|reversal|finding)s?\b|"
    r"\bno (?:comparison|pair|contrast)s?\b[^.]{0,140}"
    r"\b(?:qualif(?:y|ies|ied)|revers(?:e|es|ed|al))\b|"
    r"\bif\b[^.]{0,180}\b(?:does not|fails? to|matches?)\b",
    re.IGNORECASE,
)
ALGORITHM_MECHANISM_ISOLATION_RE = re.compile(
    r"\b(?:ablations?|remov(?:e|es|ed|ing|als?)|"
    r"(?:component|module|feature)s?[- ]"
    r"(?:analys(?:is|es)|tests?|ablations?|removals?)|"
    r"leave[- ]one[- ](?:component|module|feature)[- ]out|"
    r"matched[- ]controls?)\b|(?<!\w)w/o(?!\w)",
    re.IGNORECASE,
)

SYNTHETIC_PREVIEW_FIGURE_LABELS = (
    "fig:preview-main-comparison",
    "fig:preview-ablation",
    "fig:preview-training-dynamics",
    "fig:preview-robustness",
    "fig:preview-error-analysis",
    "fig:preview-calibration",
    "fig:preview-efficiency",
)
SYNTHETIC_PREVIEW_TABLE_LABELS = (
    "tab:preview-main-results",
    "tab:paired-reversals",
    "tab:preview-ablation",
    "tab:preview-robustness-calibration",
    "tab:preview-error-analysis",
    "tab:preview-calibration",
    "tab:preview-efficiency",
)
SYNTHETIC_PREVIEW_ANALYSIS_REQUIREMENTS = {
    "comparison and apparent ordering": (
        r"\b(?:compar(?:e|ed|ing|ison|ative)|baseline|ordering|rank(?:ing)?|"
        r"difference|interval overlap)\b"
    ),
    "training trend or convergence behavior": (
        r"\b(?:training dynamics|training (?:trend|trajectory|curve)|"
        r"learning curve|optimization trajectory|epoch|converg|plateau)"
    ),
    "component-ablation interpretation": (
        r"\b(?:ablations?|component(?:[- ]?(?:level|wise))? "
        r"(?:removals?|contributions?|effects?|controls?|diagnostics?)|"
        r"matched (?:removals?|controls?)|leave[- ]one[- ]out|remov(?:ing|als?)|"
        r"without (?:the )?(?:component|module|feature)|w/o)\b"
    ),
    "robustness or stress interpretation": (
        r"\b(?:robust|stress|shift|sensitivity|degrad|held-out condition)"
    ),
    "calibration or selective-risk interpretation": (
        r"\b(?:calibrat|coverage|selective risk|reliability)"
    ),
    "uncertainty interpretation": (
        r"\b(?:uncertainty|confidence interval|credible interval|dispersion|"
        r"variance|error bars?|uncertainty bands?|interval overlap|intervals? (?:cross zero|overlap|summarize))\b"
    ),
    "failure or error-slice interpretation": (
        r"\b(?:failure|error (?:analysis|slice|pattern)|negative case|subgroup|"
        r"degrad|weakness|worst-case)"
    ),
    "performance-resource trade-off": (
        r"\b(?:resource|efficien\w*|latency|throughput|memory|comput\w*|energy|cost\w*|"
        r"parameter|performance|quality)\b[^.]{0,140}\b(?:trade[- ]?offs?|frontier)\b|"
        r"\b(?:trade[- ]?offs?|frontier)\b[^.]{0,140}\b(?:resource|"
        r"efficien\w*|latency|throughput|memory|comput\w*|energy|cost\w*|parameter|"
        r"performance|quality)\b"
    ),
}


def synthetic_analysis_requirements(archetype: str) -> dict[str, str]:
    """Return domain-valid prose checks for the stable seven-asset package."""
    requirements = dict(SYNTHETIC_PREVIEW_ANALYSIS_REQUIREMENTS)
    domain_overrides = {
        "systems_testbed": {
            "configuration or component-sensitivity interpretation": r"\b(?:configuration|component|variant|matched|control|workload)\b",
            "scale or execution-trajectory interpretation": r"\b(?:scale|trajectory|throughput|latency|load|warm-up|tail)\b",
        },
        "observational_cohort": {
            "specification-sensitivity interpretation": r"\b(?:adjust|specification|confound|covariate|sensitivity|subgroup)\b",
            "validation-trajectory interpretation": r"\b(?:validation|cohort|fraction|sample size|stability|trajectory)\b",
        },
        "diagnostic_prognostic": {
            "model or threshold-sensitivity interpretation": r"\b(?:threshold|predictor|calibrat|specification|sensitivity|subgroup)\b",
            "validation-trajectory interpretation": r"\b(?:validation|external|fraction|trajectory|discrimination|utility)\b",
        },
        "intervention_trial": {
            "estimand or protocol-sensitivity interpretation": r"\b(?:estimand|protocol|adherence|deviation|treatment|intervention|sensitivity)\b",
            "follow-up or information-trajectory interpretation": r"\b(?:follow-up|information|completeness|trajectory|participant|outcome)\b",
        },
        "omics_discovery": {
            "pipeline or assay-sensitivity interpretation": r"\b(?:assay|batch|pipeline|quality control|filter|sensitivity)\b",
            "validation-trajectory interpretation": r"\b(?:validation|replicate|sample|trajectory|discovery|orthogonal)\b",
        },
        "controlled_experiment": {
            "factor or control-sensitivity interpretation": r"\b(?:factor|control|condition|perturb|dose|replicate|sensitivity)\b",
            "dose, time, or replicate-trajectory interpretation": r"\b(?:dose|time|replicate|trajectory|response|converg)\b",
        },
        "simulation_modeling": {
            "parameter or assumption-sensitivity interpretation": r"\b(?:parameter|boundary|assumption|sensitivity|identifiab)\b",
            "verification or convergence interpretation": r"\b(?:verification|converg|resolution|discret|trajectory|solver)\b",
        },
        "formal_theory": {
            "assumption-necessity interpretation": r"\b(?:assumption|necessity|removed|relax|lemma|condition)\b",
            "proof or verification progression": r"\b(?:proof|verification|derivation|construction|stage|lemma|progression)\b",
            "counterexample or boundary interpretation": r"\b(?:counterexample|boundary|impossibility|limiting|failure)\b",
            "proof-complexity trade-off": r"\b(?:proof|verification|complexity|assumption|burden)\b[^.]{0,120}\btrade[- ]?off\b|\btrade[- ]?off\b[^.]{0,120}\b(?:proof|verification|complexity|assumption|burden)\b",
        },
        "qualitative_mixed": {
            "coding or triangulation-sensitivity interpretation": r"\b(?:coding|triangulat|coder|interpret|sensitivity)\b",
            "saturation progression": r"\b(?:saturation|cases reviewed|case accumulation|progression|theme)\b",
            "divergent or negative-case interpretation": r"\b(?:divergent|negative case|disagreement|rival|contradiction)\b",
            "auditability or coding-burden trade-off": r"\b(?:auditab|coding|coder|burden|traceab)\b[^.]{0,120}\btrade[- ]?off\b|\btrade[- ]?off\b[^.]{0,120}\b(?:auditab|coding|coder|burden|traceab)\b",
        },
    }
    overrides = domain_overrides.get(str(archetype or "").casefold())
    if not overrides:
        return requirements
    requirements.pop("training trend or convergence behavior", None)
    requirements.pop("component-ablation interpretation", None)
    if archetype == "formal_theory":
        requirements.pop("failure or error-slice interpretation", None)
        requirements.pop("performance-resource trade-off", None)
    elif archetype == "qualitative_mixed":
        requirements.pop("failure or error-slice interpretation", None)
        requirements.pop("performance-resource trade-off", None)
    requirements.update(overrides)
    return requirements
class PaperDraftingService(PaperDraftStateMixin):
    """Own the durable manuscript state; model sessions only author bounded files."""

    # One directed transaction gets one model edit against one exact artifact
    # state. The outer workflow may call again only after the target bytes have
    # genuinely changed. This prevents a nested retry loop from spending two
    # calls on identical findings and then reporting semantic no-progress.
    DIRECTED_REPAIR_ATTEMPTS = 1
    # Initial authoring has no outer targeted transaction yet. Permit two
    # unchanged post-write validations before stopping that local loop.
    SEMANTIC_NO_PROGRESS_ATTEMPTS = 2

    AUTHORING_SOURCE_PATHS = paper_draft_state.AUTHORING_SOURCE_PATHS
    DERIVED_SOURCE_PATHS = paper_draft_state.DERIVED_SOURCE_PATHS

    def build_style_profile(
        self, project_path: str | Path,
        options: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        from .paper_draft_contracts import build_style_profile

        root = self.paths(project_path)["root"]
        return build_style_profile(
            root, options, analyse_source=self.analyse_tex_source,
            schema=STYLE_PROFILE_SCHEMA_VERSION, exemplars=BUILTIN_EXEMPLARS,
        )

    def build_contracts(
        self, project_path: str | Path,
        options: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        from .paper_draft_contracts import build_section_contracts

        root = self.paths(project_path)["root"]
        return build_section_contracts(
            root, options, specs=SECTION_SPECS, author_order=AUTHOR_STAGE_ORDER,
            schema=SECTION_CONTRACT_SCHEMA_VERSION,
            source_signature=self.source_signature,
            authoring_signature=self.authoring_signature,
        )
    def prepare(
        self, project_path: str | Path,
        options: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        from .paper_draft_preparation import prepare_draft_state

        paths = self.paths(project_path)
        paths["paper"].mkdir(parents=True, exist_ok=True)
        paths["sections"].mkdir(parents=True, exist_ok=True)
        self.build_style_profile(project_path, options)
        contracts = self.build_contracts(project_path, options)
        return prepare_draft_state(
            project_path, options, paths=paths, contracts=contracts,
            author_stages=AUTHOR_STAGE_ORDER, stage_outputs=self.stage_outputs,
            freeze_inputs=self.freeze_scientific_inputs,
            draft_schema=DRAFT_SCHEMA_VERSION,
            section_contract=SECTION_CONTRACT_SCHEMA_VERSION,
            consistency_contract=CONSISTENCY_CONTRACT_VERSION,
            assembly_contract=ASSEMBLY_CONTRACT_VERSION,
        )
    @staticmethod
    def stage_outputs(paths: dict[str, Path], stage_id: str) -> list[Path]:
        from .paper_draft_stages import stage_outputs

        return stage_outputs(paths, stage_id, SECTION_BY_ID)

    @classmethod
    def stage_for_project_relative_target(cls, target: str) -> str:
        from .paper_draft_stages import stage_for_target

        return stage_for_target(target, SECTION_SPECS)

    @classmethod
    def revision_target_paths(cls, issues: Iterable[str]) -> list[str]:
        from .paper_draft_stages import revision_target_paths

        return revision_target_paths(issues)

    @staticmethod
    def stage_contract_version(stage_id: str) -> int:
        from .paper_draft_stages import stage_contract_version

        return stage_contract_version(
            stage_id, SECTION_CONTRACT_SCHEMA_VERSION,
            CONSISTENCY_CONTRACT_VERSION, ASSEMBLY_CONTRACT_VERSION,
        )

    @classmethod
    def stage_write_targets(
        cls, paths: dict[str, Path], stage_id: str,
    ) -> list[Path]:
        from .paper_draft_stages import stage_write_targets

        return stage_write_targets(
            paths, stage_id, section_by_id=SECTION_BY_ID,
            author_order=AUTHOR_STAGE_ORDER,
        )

    @classmethod
    def stage_target_semantic_signature(
        cls, paths: dict[str, Path], stage_id: str,
    ) -> str:
        from .paper_draft_stages import target_semantic_signature

        return target_semantic_signature(
            paths, cls.stage_write_targets(paths, stage_id)
        )

    def stage_input_signature(self, paths: dict[str, Path], stage_id: str) -> str:
        from .paper_draft_stages import stage_input_signature

        return stage_input_signature(
            paths, stage_id, author_order=AUTHOR_STAGE_ORDER,
            section_by_id=SECTION_BY_ID,
        )

    @staticmethod
    def stage_validator_signature(stage_id: str) -> str:
        from .paper_stage_validator_signature import stage_validator_signature

        return stage_validator_signature(stage_id)

    def stage_is_current(
        self, paths: dict[str, Path], state: dict[str, Any], stage_id: str,
    ) -> bool:
        from .paper_draft_stages import stage_outputs_match

        record = dict(state.get("stages", {}).get(stage_id) or {})
        return bool(
            stage_outputs_match(
                self.stage_outputs(paths, stage_id), record,
                self.stage_contract_version(stage_id), stage_id,
            )
            and record.get("input_signature")
            == self.stage_input_signature(paths, stage_id)
        )

    def stage_outputs_are_current(
        self, paths: dict[str, Path], state: dict[str, Any], stage_id: str,
    ) -> bool:
        from .paper_draft_stages import stage_outputs_match

        record = dict(state.get("stages", {}).get(stage_id) or {})
        return stage_outputs_match(
            self.stage_outputs(paths, stage_id), record,
            self.stage_contract_version(stage_id), stage_id,
        )

    @staticmethod
    def inventory(paths: Iterable[Path], root: Path) -> str:
        from .paper_draft_stages import inventory

        return inventory(paths, root)

    @staticmethod
    def write_authoring_asset_manifest(
        root: Path, target: Path, *, evidence_mode: str,
    ) -> Path:
        from .paper_draft_stages import write_authoring_asset_manifest

        return write_authoring_asset_manifest(
            root, target, evidence_mode=evidence_mode
        )
    def build_stage_prompt(
        self, project_path: str | Path, stage_id: str,
        options: Optional[dict[str, Any]] = None,
        revision_issues: Optional[list[str]] = None,
    ) -> str:
        from .paper_stage_prompts import build_stage_prompt

        return build_stage_prompt(
            paths=self.paths(project_path), stage_id=stage_id, options=options,
            revision_issues=revision_issues, section_by_id=SECTION_BY_ID,
            author_order=AUTHOR_STAGE_ORDER, inventory=self.inventory,
            write_assets=self.write_authoring_asset_manifest,
        )
    @staticmethod
    def invocation_contract(stage_id: str, output_paths: Iterable[Path]) -> str:
        from .paper_stage_validation import invocation_contract

        return invocation_contract(stage_id, output_paths)

    def validate_blueprint(self, path: Path) -> dict[str, Any]:
        from .paper_stage_validation import validate_blueprint

        return validate_blueprint(path)

    def validate_front_matter(
        self, paths: dict[str, Path], evidence: dict[str, Any],
    ) -> dict[str, Any]:
        from .paper_stage_validation import validate_front_matter

        return validate_front_matter(
            paths, evidence, admin_pattern=ADMIN_RE,
            superiority_pattern=SUPERIORITY_RE,
        )
    @staticmethod
    def falsifiable_contribution_structure(text: str) -> dict[str, int]:
        from .paper_contribution_validation import falsifiable_contribution_structure

        return falsifiable_contribution_structure(text)
    def section_review(
        self, root: Path, spec: SectionSpec, evidence: dict[str, Any],
        required_mechanisms: list[str],
    ) -> dict[str, Any]:
        from .paper_section_review import (
            SectionReviewPolicy,
            review_section,
        )

        policy = SectionReviewPolicy(
            admin=ADMIN_RE, ai_ism=AI_ISM_RE, superiority=SUPERIORITY_RE,
            algorithm_mechanism=ALGORITHM_MECHANISM_ISOLATION_RE,
            alternative_explanation=ALTERNATIVE_EXPLANATION_RE,
            negative_result=NEGATIVE_RESULT_RE,
            preview_figure_labels=SYNTHETIC_PREVIEW_FIGURE_LABELS,
            preview_table_labels=SYNTHETIC_PREVIEW_TABLE_LABELS,
            synthetic_analysis_requirements=synthetic_analysis_requirements,
        )
        return review_section(root, spec, evidence, required_mechanisms, policy)
    def validate_stage(
        self, project_path: str | Path, stage_id: str,
    ) -> dict[str, Any]:
        from .paper_stage_lifecycle import validate_stage

        return validate_stage(
            project_path, stage_id, paths=self.paths(project_path),
            section_by_id=SECTION_BY_ID,
            validate_blueprint=self.validate_blueprint,
            validate_front_matter=self.validate_front_matter,
            validate_complete=self.validate_complete_draft,
            review_section=self.section_review,
        )
    def record_review(
        self, paths: dict[str, Path], stage_id: str,
        review: dict[str, Any], attempt: int,
    ) -> None:
        from .paper_stage_lifecycle import record_review

        record_review(
            paths, stage_id, review, attempt,
            section_ids=set(SECTION_BY_ID),
        )
    def mark_stage(
        self, paths: dict[str, Path], stage_id: str, status: str, *,
        attempt: Optional[int] = None, review: Optional[dict[str, Any]] = None,
        error: str = "",
    ) -> dict[str, Any]:
        from .paper_stage_lifecycle import mark_stage

        return mark_stage(
            paths, stage_id, status, attempt=attempt, review=review, error=error,
            section_ids=set(SECTION_BY_ID), author_order=AUTHOR_STAGE_ORDER,
            section_contract_version=SECTION_CONTRACT_SCHEMA_VERSION,
            stage_outputs=self.stage_outputs,
            input_signature=self.stage_input_signature,
            contract_version=self.stage_contract_version,
        )
    def reconcile_reviewed_artifacts(
        self, project_path: str | Path, *,
        reviewer: str = "cross-model-review",
    ) -> dict[str, Any]:
        from .paper_review_reconciliation import reconcile_reviewed_artifacts

        return reconcile_reviewed_artifacts(
            project_path, reviewer=reviewer, paths=self.paths(project_path),
            draft_schema=DRAFT_SCHEMA_VERSION, author_order=AUTHOR_STAGE_ORDER,
            consistency_version=CONSISTENCY_CONTRACT_VERSION,
            assembly_version=ASSEMBLY_CONTRACT_VERSION,
            validate_stage=self.validate_stage,
            validate_complete=self.validate_complete_draft,
            assemble=self.assemble, stage_outputs=self.stage_outputs,
            input_signature=self.stage_input_signature,
            contract_version=self.stage_contract_version,
        )
    def refresh_deterministic_assembly(
        self, project_path: str | Path,
    ) -> dict[str, Any]:
        from .paper_review_reconciliation import refresh_deterministic_assembly

        return refresh_deterministic_assembly(
            project_path, paths=self.paths(project_path),
            draft_schema=DRAFT_SCHEMA_VERSION, author_order=AUTHOR_STAGE_ORDER,
            assembly_version=ASSEMBLY_CONTRACT_VERSION,
            stage_is_current=self.stage_is_current, assemble=self.assemble,
            validate_complete=self.validate_complete_draft,
        )
    @staticmethod
    def canonical_venue(value: Any) -> str:
        from .paper_venue_templates import canonical_venue

        return canonical_venue(value)

    @staticmethod
    def canonical_venue_family(
        requested_venue: str, publication_style: dict[str, Any],
    ) -> str:
        from .paper_venue_templates import canonical_venue_family

        return canonical_venue_family(requested_venue, publication_style)

    @staticmethod
    def template_source_fingerprint(source_path: str | Path) -> str:
        from .paper_venue_templates import template_source_fingerprint

        return template_source_fingerprint(source_path, CUSTOM_TEMPLATE_EXTENSIONS)

    @staticmethod
    def _template_roots() -> tuple[Path, ...]:
        from .paper_venue_templates import template_roots

        return template_roots(Path(__file__))

    def install_venue_assets(
        self, paper_root: Path, venue_key: str,
    ) -> dict[str, Any]:
        from .paper_venue_templates import install_venue_assets

        return install_venue_assets(
            paper_root, venue_key, bundles=VENUE_TEMPLATE_BUNDLES,
            roots=self._template_roots(), error_factory=PaperDraftingError,
        )

    @staticmethod
    def _choose_custom_template_main(
        snapshot_root: Path, preferred: Optional[Path] = None,
    ) -> Optional[Path]:
        from .paper_venue_templates import choose_custom_template_main

        return choose_custom_template_main(snapshot_root, preferred)

    def install_custom_venue_template(
        self, paper_root: Path, source_value: str,
    ) -> tuple[dict[str, Any], str, str]:
        from .paper_venue_templates import install_custom_venue_template

        return install_custom_venue_template(
            paper_root, source_value, extensions=CUSTOM_TEMPLATE_EXTENSIONS,
            dependency_extensions=CUSTOM_TEMPLATE_DEPENDENCY_EXTENSIONS,
            reserved_targets=CUSTOM_TEMPLATE_RESERVED_TARGETS,
            error_factory=PaperDraftingError,
        )
    def assemble(self, project_path: str | Path) -> Path:
        from .paper_manuscript_assembly import assemble_manuscript

        return assemble_manuscript(
            paths=self.paths(project_path), specs=SECTION_SPECS,
            venue_bundles=VENUE_TEMPLATE_BUNDLES,
            family_bundles=VENUE_FAMILY_BUNDLES,
            content_markers=CUSTOM_TEMPLATE_CONTENT_MARKERS,
            disclosure_title=SIMULATION_END_DISCLOSURE_TITLE,
            disclosure_text=SIMULATION_END_DISCLOSURE,
            canonical_venue=self.canonical_venue,
            canonical_family=self.canonical_venue_family,
            install_venue=self.install_venue_assets,
            install_custom=self.install_custom_venue_template,
            error_factory=PaperDraftingError,
        )
    def validate_complete_draft(
        self, project_path: str | Path, *, require_main: bool = True,
    ) -> dict[str, Any]:
        from .paper_complete_validation import validate_complete_draft

        return validate_complete_draft(
            paths=self.paths(project_path), specs=SECTION_SPECS,
            require_main=require_main, superiority_pattern=SUPERIORITY_RE,
            section_review=self.section_review,
            front_matter_review=self.validate_front_matter,
        )
    def gate_report(
        self, project_path: str | Path,
        options: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        from .paper_gate_reporting import gate_report

        return gate_report(
            project_path, options, paths=self.paths(project_path),
            draft_schema=DRAFT_SCHEMA_VERSION, author_order=AUTHOR_STAGE_ORDER,
            assembly_version=ASSEMBLY_CONTRACT_VERSION,
            stage_labels=PAPER_STAGE_LABELS, venue_bundles=VENUE_TEMPLATE_BUNDLES,
            stage_is_current=self.stage_is_current,
            stage_outputs=self.stage_outputs,
            stage_contract_version=self.stage_contract_version,
            target_signature=self.stage_target_semantic_signature,
            issue_signature=self.directed_issue_signature,
            gate_options=self.gate_signature_options,
            validate_freeze=self.validate_scientific_freeze,
            source_signature=self.source_signature,
            authoring_signature=self.authoring_signature,
            canonical_venue=self.canonical_venue,
            canonical_family=self.canonical_venue_family,
            template_fingerprint=self.template_source_fingerprint,
            validate_complete=self.validate_complete_draft,
        )
    async def draft(
        self, project_path: str | Path, direction: str, options: dict[str, Any],
        invoke_stage: StageInvoker, emit: Optional[EventEmitter] = None, *,
        revision_issues: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        from .paper_draft_coordinator import DraftCoordinator

        coordinator = DraftCoordinator(
            service=self, project_path=project_path, direction=direction,
            options=options, invoke_stage=invoke_stage, emit=emit,
            revision_issues=revision_issues, paths=self.paths(project_path),
            author_order=AUTHOR_STAGE_ORDER, paper_stage_order=PAPER_STAGE_ORDER,
            section_by_id=SECTION_BY_ID, stage_labels=PAPER_STAGE_LABELS,
            error_factory=PaperDraftingError,
            directed_repair_attempts=self.DIRECTED_REPAIR_ATTEMPTS,
            semantic_stall_attempts=self.SEMANTIC_NO_PROGRESS_ATTEMPTS,
        )
        return await coordinator.run()


paper_drafting_service = PaperDraftingService()
