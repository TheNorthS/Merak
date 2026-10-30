"""Domain-aware visual and reporting contracts for research manuscripts."""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

from ..utils.atomic_write import atomic_write_json
from .publication_style_payload import ranked_matches, style_payload
from .publication_constants import (
    FIELD_ADAPTIVE_VISUAL_GUIDE,
    IMPLEMENTATION_FAMILY_BY_RESEARCH_FAMILY,
    NATURE_FIGURE_GUIDE_URL,
    NATURE_PANEL_GUIDE_URL,
)


STYLE_SCHEMA_VERSION = 2
# These are deliberately expressed as contracts rather than plotting
# templates.  Downstream stages can use them for prompts and deterministic
# checks without leaking an internal "synthetic" or submission-status label
# into the manuscript.
from .publication_evidence_contracts import DOMAIN_EVIDENCE_CONTRACTS

ACCESSIBLE_PALETTE = {
    "blue": "#0072B2",
    "orange": "#E69F00",
    "green": "#009E73",
    "vermillion": "#D55E00",
    "purple": "#CC79A7",
    "sky": "#56B4E9",
    "black": "#222222",
    "grey": "#6B7280",
    "light_grey": "#D1D5DB",
}


FAMILY_SPECS: dict[str, dict[str, Any]] = {
    "machine_learning": {
        "label": "Machine learning and computational modeling",
        "keywords": (
            "machine learning", "deep learning", "neural network", "transformer",
            "foundation model", "representation learning", "computer vision",
            "natural language", "reinforcement learning", "benchmark",
        ),
        "figure_roles": [
            ("method", "Mechanism-level architecture"),
            ("evaluation_design", "Dataset, split, and evaluation protocol"),
            ("main_comparison", "Benchmark comparison with uncertainty"),
            ("ablation", "Component and matched-capacity ablations"),
            ("robustness_or_error_analysis", "Robustness, scaling, or error slices"),
            ("calibration_or_efficiency", "Calibration, efficiency, or scaling"),
        ],
        "table_roles": [
            ("dataset_summary", "Datasets, tasks, splits, and units"),
            ("main_results", "Main benchmark with uncertainty"),
            ("ablation", "Component and control ablations"),
            ("robustness_or_calibration", "Stress and calibration endpoints"),
            ("efficiency", "Parameters, compute, and latency"),
        ],
        "reporting": {
            "secondary_label": "Secondary metric",
            "stress_label": "Worst-shift score",
            "calibration_label": "Calibration error (lower)",
            "effect_label": "Mean score",
        },
        "plot_types": ["interval_comparison", "stress_curve", "risk_coverage"],
    },
    "computer_systems": {
        "label": "Computer systems, software, security, and HCI",
        "keywords": (
            "software engineering", "program analysis", "database", "query optimizer",
            "operating system", "distributed system", "computer network", "cybersecurity",
            "security", "privacy", "cryptography", "compiler", "programming language",
            "human-computer interaction", "hci", "usability", "cloud computing",
        ),
        "figure_roles": [
            ("method", "System design, threat model, or interaction architecture"),
            ("evaluation_design", "Testbed, workload, participants, and protocol"),
            ("main_comparison", "Primary effectiveness and performance comparison"),
            ("robustness_or_error_analysis", "Scale, attack, failure, or user-error analysis"),
            ("calibration_or_efficiency", "Latency, throughput, cost, or usability trade-off"),
        ],
        "table_roles": [
            ("dataset_summary", "Systems, workloads, datasets, or participant characteristics"),
            ("main_results", "Primary effectiveness and performance results"),
            ("ablation", "Component, configuration, and matched-control analysis"),
            ("robustness_or_calibration", "Scale, threat, sensitivity, and failure cases"),
            ("efficiency", "Latency, throughput, memory, energy, and cost"),
        ],
        "reporting": {
            "secondary_label": "System utility / quality",
            "stress_label": "Worst workload / threat",
            "calibration_label": "Resource or user cost",
            "effect_label": "Primary system metric",
        },
        "plot_types": ["tradeoff_frontier", "scaling_curve", "tail_latency"],
    },
    "computational_biology": {
        "label": "Bioinformatics and computational biology",
        "keywords": (
            "bioinformatics", "computational biology", "genomics", "transcriptomics",
            "proteomics", "metagenomics", "single-cell", "scrna", "gene expression",
            "pathway", "variant", "gwas", "multi-omics", "molecular", "protein",
        ),
        "figure_roles": [
            ("evaluation_design", "Cohort, sample, and filtering flow"),
            ("method", "Model or analysis workflow"),
            ("main_comparison", "Primary effect or predictive estimate"),
            ("robustness_or_error_analysis", "External cohort and sensitivity analysis"),
            ("calibration_or_efficiency", "Biological interpretation or pathway analysis"),
        ],
        "table_roles": [
            ("dataset_summary", "Cohorts, samples, assays, and exclusions"),
            ("main_results", "Primary effect estimates and uncertainty"),
            ("ablation", "Feature, model, and sensitivity controls"),
            ("robustness_or_calibration", "External validation and calibration"),
            ("efficiency", "Runtime, memory, and reproducibility details"),
        ],
        "reporting": {
            "secondary_label": "External validation",
            "stress_label": "Worst-cohort estimate",
            "calibration_label": "Adjusted significance / error",
            "effect_label": "Effect estimate",
        },
        "plot_types": ["forest_effect", "cohort_sensitivity", "calibration"],
    },
    "clinical_biomedical": {
        "label": "Clinical and biomedical research",
        "keywords": (
            "clinical", "patient", "medical", "diagnosis", "prognosis", "survival",
            "hospital", "trial", "treatment", "biomarker", "sensitivity", "specificity",
            "cohort", "case-control", "randomized",
        ),
        "figure_roles": [
            ("evaluation_design", "Cohort or participant flow"),
            ("method", "Model, intervention, or analysis workflow"),
            ("main_comparison", "Primary clinical endpoint and effect estimate"),
            ("robustness_or_error_analysis", "Subgroup, external, and sensitivity analysis"),
            ("calibration_or_efficiency", "Calibration, decision utility, or survival"),
        ],
        "table_roles": [
            ("dataset_summary", "Participant characteristics and exclusions"),
            ("main_results", "Primary endpoint with confidence intervals"),
            ("ablation", "Adjusted, unadjusted, and sensitivity models"),
            ("robustness_or_calibration", "Subgroup, calibration, and external validation"),
            ("efficiency", "Deployment and reproducibility characteristics"),
        ],
        "reporting": {
            "secondary_label": "External validation",
            "stress_label": "Worst subgroup",
            "calibration_label": "Calibration / decision utility",
            "effect_label": "Effect estimate",
        },
        "plot_types": ["forest_effect", "subgroup_forest", "calibration"],
    },
    "experimental_natural_science": {
        "label": "Experimental natural science",
        "keywords": (
            "chemistry", "physics", "materials", "nanomaterial", "catalysis",
            "spectroscopy", "microscopy", "ecology", "climate", "geoscience",
            "laboratory", "assay", "concentration", "dose-response",
        ),
        "figure_roles": [
            ("evaluation_design", "Experimental design and sample flow"),
            ("method", "Mechanism or measurement workflow"),
            ("main_comparison", "Primary effect with replicate distribution"),
            ("robustness_or_error_analysis", "Dose, time, or perturbation response"),
            ("calibration_or_efficiency", "Mechanistic or orthogonal validation"),
        ],
        "table_roles": [
            ("dataset_summary", "Samples, conditions, and replicates"),
            ("main_results", "Primary measurements and effect sizes"),
            ("ablation", "Control conditions and sensitivity analysis"),
            ("robustness_or_calibration", "Orthogonal and reproducibility checks"),
            ("efficiency", "Materials, instrument, and acquisition details"),
        ],
        "reporting": {
            "secondary_label": "Orthogonal validation",
            "stress_label": "Worst condition",
            "calibration_label": "Relative error",
            "effect_label": "Effect size",
        },
        "plot_types": ["dot_interval", "dose_response", "replicate_distribution"],
    },
    "social_behavioral": {
        "label": "Social, behavioral, and quantitative sciences",
        "keywords": (
            "psychology", "behavioral", "social science", "economics", "education",
            "survey study", "questionnaire", "participant", "causal", "treatment effect", "policy",
        ),
        "figure_roles": [
            ("evaluation_design", "Participant or sampling flow"),
            ("method", "Study design and analysis model"),
            ("main_comparison", "Primary estimate with uncertainty"),
            ("robustness_or_error_analysis", "Specification and subgroup robustness"),
            ("calibration_or_efficiency", "Heterogeneity or marginal effects"),
        ],
        "table_roles": [
            ("dataset_summary", "Sample, variables, and exclusions"),
            ("main_results", "Primary estimates and uncertainty"),
            ("ablation", "Alternative specifications and controls"),
            ("robustness_or_calibration", "Subgroups and sensitivity analyses"),
            ("efficiency", "Data and analysis reproducibility"),
        ],
        "reporting": {
            "secondary_label": "Adjusted estimate",
            "stress_label": "Sensitivity estimate",
            "calibration_label": "Model fit / uncertainty",
            "effect_label": "Estimate",
        },
        "plot_types": ["coefficient_plot", "subgroup_forest", "sensitivity"],
    },
    "engineering_systems": {
        "label": "Engineering, systems, and robotics",
        "keywords": (
            "robotics", "control", "autonomous", "embedded", "network", "distributed",
            "manufacturing", "power system", "mechanical", "hardware", "latency",
            "throughput", "simulation",
        ),
        "figure_roles": [
            ("method", "System architecture and data path"),
            ("evaluation_design", "Testbed, workload, and protocol"),
            ("main_comparison", "Quality and performance comparison"),
            ("robustness_or_error_analysis", "Stress, scale, and failure analysis"),
            ("calibration_or_efficiency", "Latency, energy, and resource scaling"),
        ],
        "table_roles": [
            ("dataset_summary", "Testbed, workloads, and operating conditions"),
            ("main_results", "Quality, performance, and uncertainty"),
            ("ablation", "Component and control configurations"),
            ("robustness_or_calibration", "Stress and failure modes"),
            ("efficiency", "Latency, throughput, memory, and energy"),
        ],
        "reporting": {
            "secondary_label": "Throughput / utility",
            "stress_label": "Worst-case quality",
            "calibration_label": "Latency (lower)",
            "effect_label": "Primary performance",
        },
        "plot_types": ["interval_comparison", "stress_curve", "scaling"],
    },
    "theoretical_formal": {
        "label": "Mathematics, theory, and formal methods",
        "keywords": (
            "theorem", "lemma", "proof", "formal verification", "complexity bound",
            "convergence rate", "mathematical", "topology", "algebra", "optimization theory",
            "stability proof", "identifiability", "asymptotic", "lower bound", "upper bound",
        ),
        "figure_roles": [
            ("method", "Definitions, construction, or proof dependency map"),
            ("evaluation_design", "Assumption and theorem applicability map"),
            ("main_comparison", "Bound, convergence, or illustrative counterexample"),
            ("robustness_or_error_analysis", "Assumption sensitivity or limiting cases"),
            ("calibration_or_efficiency", "Computational or sample-complexity implications"),
        ],
        "table_roles": [
            ("dataset_summary", "Notation, assumptions, and problem classes"),
            ("main_results", "Theorems, guarantees, and comparison bounds"),
            ("ablation", "Necessity of assumptions and counterexamples"),
            ("robustness_or_calibration", "Boundary cases and failure conditions"),
            ("efficiency", "Complexity and convergence summary"),
        ],
        "reporting": {
            "secondary_label": "Corollary / implication",
            "stress_label": "Boundary case",
            "calibration_label": "Complexity / bound",
            "effect_label": "Guarantee",
        },
        "plot_types": ["bound_comparison", "phase_diagram", "counterexample"],
    },
    "qualitative_humanities": {
        "label": "Qualitative, humanities, and mixed-methods research",
        "keywords": (
            "qualitative", "interview", "focus group", "ethnography", "thematic analysis",
            "grounded theory", "discourse analysis", "historical analysis", "case study",
            "mixed methods", "content analysis", "archive", "humanities",
        ),
        "figure_roles": [
            ("evaluation_design", "Case, corpus, participant, and sampling flow"),
            ("method", "Coding, interpretation, and triangulation process"),
            ("main_comparison", "Theme, case, or mixed-method convergence map"),
            ("robustness_or_error_analysis", "Negative cases, rival readings, and sensitivity"),
            ("calibration_or_efficiency", "Triangulation and reflexivity evidence"),
        ],
        "table_roles": [
            ("dataset_summary", "Cases, participants, corpus, and sampling rationale"),
            ("main_results", "Themes, evidence excerpts, and case contrasts"),
            ("ablation", "Alternative coding or interpretation checks"),
            ("robustness_or_calibration", "Negative cases and triangulation"),
            ("efficiency", "Audit trail and analytic provenance"),
        ],
        "reporting": {
            "secondary_label": "Triangulating source",
            "stress_label": "Negative case",
            "calibration_label": "Agreement / reflexivity",
            "effect_label": "Theme or case evidence",
        },
        "plot_types": ["evidence_matrix", "theme_map", "case_comparison"],
    },
    "generic_quantitative": {
        "label": "Quantitative research",
        "keywords": (),
        "figure_roles": [
            ("evaluation_design", "Study design and analysis units"),
            ("method", "Method or causal workflow"),
            ("main_comparison", "Primary estimate with uncertainty"),
            ("robustness_or_error_analysis", "Robustness and error analysis"),
            ("calibration_or_efficiency", "Sensitivity or efficiency"),
        ],
        "table_roles": [
            ("dataset_summary", "Study design and data summary"),
            ("main_results", "Primary estimate with uncertainty"),
            ("ablation", "Alternative specifications or components"),
            ("robustness_or_calibration", "Robustness and sensitivity"),
            ("efficiency", "Reproducibility and resource details"),
        ],
        "reporting": {
            "secondary_label": "Secondary endpoint",
            "stress_label": "Worst-case estimate",
            "calibration_label": "Uncertainty / error",
            "effect_label": "Estimate",
        },
        "plot_types": ["interval_comparison", "sensitivity", "calibration"],
    },
}


STUDY_ARCHETYPE_SPECS: dict[str, dict[str, Any]] = {
    "algorithm_benchmark": {
        "keywords": ("benchmark", "baseline", "ablation", "model", "algorithm", "prediction"),
        "reporting_standards": ["ML reproducibility and dataset documentation"],
        "required_evidence": [
            "leakage-safe data splits and independent analysis units",
            "strong and compute-matched baselines",
            "multi-run uncertainty, ablation, robustness, and resource accounting",
        ],
        "section_emphasis": ["method", "experimental setup", "results", "limitations"],
        "plot_types": ["interval_comparison", "critical_difference", "scaling_curve"],
    },
    "observational_cohort": {
        "keywords": ("cohort", "observational", "retrospective", "prospective", "case-control"),
        "reporting_standards": ["STROBE"],
        "required_evidence": [
            "participant or sample flow with inclusion and exclusion criteria",
            "confounder plan, missing-data handling, effect sizes, and confidence intervals",
            "sensitivity analysis and external or temporal validation when available",
        ],
        "section_emphasis": ["methods", "cohort characteristics", "primary analysis", "sensitivity"],
        "plot_types": ["cohort_flow", "forest_effect", "sensitivity"],
    },
    "diagnostic_prognostic": {
        "keywords": ("diagnosis", "diagnostic", "prognosis", "prognostic", "biomarker", "survival"),
        "reporting_standards": ["TRIPOD", "STARD"],
        "required_evidence": [
            "target population, outcome timing, and reference standard",
            "discrimination, calibration, clinical utility, and uncertainty",
            "external validation and subgroup performance without test-set tuning",
        ],
        "section_emphasis": ["participants", "model development", "validation", "clinical utility"],
        "plot_types": ["forest_effect", "calibration", "decision_curve"],
    },
    "intervention_trial": {
        "keywords": ("randomized", "randomised", "trial", "intervention", "treatment", "placebo"),
        "reporting_standards": ["CONSORT"],
        "required_evidence": [
            "allocation, masking, participant flow, preregistered outcomes, and harms",
            "intention-to-treat analysis with effect sizes and confidence intervals",
            "protocol deviations, missing outcomes, and multiplicity control",
        ],
        "section_emphasis": ["trial design", "participants", "outcomes", "harms"],
        "plot_types": ["participant_flow", "forest_effect", "time_to_event"],
    },
    "omics_discovery": {
        "keywords": ("genomics", "transcriptomics", "proteomics", "metagenomics", "single-cell", "multi-omics"),
        "reporting_standards": ["MIAME/MINSEQE", "FAIR data principles"],
        "required_evidence": [
            "sample provenance, assay quality control, batch handling, and filtering flow",
            "multiple-testing control and effect sizes, not significance alone",
            "independent cohort or orthogonal biological validation",
        ],
        "section_emphasis": ["samples and assays", "quality control", "discovery", "biological validation"],
        "plot_types": ["cohort_flow", "volcano_effect", "pathway_enrichment"],
    },
    "controlled_experiment": {
        "keywords": (
            "controlled experiment", "laboratory assay", "dose-response", "assay",
            "biological replicate", "technical replicate", "control group",
        ),
        "reporting_standards": ["ARRIVE where animal research applies"],
        "required_evidence": [
            "biological versus technical replicates, randomization, blinding, and exclusions",
            "raw replicate distributions, effect sizes, uncertainty, and negative controls",
            "orthogonal validation and reproducible acquisition conditions",
        ],
        "section_emphasis": ["materials and methods", "controls", "primary result", "mechanism"],
        "plot_types": ["replicate_distribution", "dose_response", "time_course"],
    },
    "systems_testbed": {
        "keywords": ("testbed", "throughput", "latency", "workload", "deployment", "hardware", "robotics"),
        "reporting_standards": ["artifact and reproducibility checklist"],
        "required_evidence": [
            "hardware, software, workload, warm-up, repetition, and measurement protocol",
            "tail behavior, scale, failures, resource use, and cost-quality trade-offs",
            "matched configurations and statistically valid repeated measurements",
        ],
        "section_emphasis": ["system design", "implementation", "evaluation", "failure analysis"],
        "plot_types": ["tail_latency", "scaling_curve", "tradeoff_frontier"],
    },
    "simulation_modeling": {
        "keywords": ("simulation", "numerical", "finite element", "agent-based", "digital twin", "modeling"),
        "reporting_standards": ["verification, validation, and uncertainty quantification"],
        "required_evidence": [
            "governing assumptions, discretization, convergence, and parameter provenance",
            "verification against analytic or manufactured solutions when possible",
            "validation, sensitivity, identifiability, and uncertainty propagation",
        ],
        "section_emphasis": ["model formulation", "verification", "validation", "sensitivity"],
        "plot_types": ["convergence", "phase_diagram", "sensitivity"],
    },
    "formal_theory": {
        "keywords": ("theorem", "proof", "lemma", "formal", "lower bound", "convergence proof"),
        "reporting_standards": ["formal definitions and proof dependency audit"],
        "required_evidence": [
            "explicit definitions, assumptions, theorem statements, and dependency order",
            "proofs or machine-checkable artifacts where claimed",
            "counterexamples and necessity of assumptions",
        ],
        "section_emphasis": ["preliminaries", "main results", "proofs", "implications"],
        "plot_types": ["proof_dependency", "bound_comparison", "counterexample"],
    },
    "qualitative_mixed": {
        "keywords": ("qualitative", "interview", "ethnography", "thematic", "mixed methods", "case study"),
        "reporting_standards": ["COREQ or SRQR where applicable"],
        "required_evidence": [
            "sampling rationale, researcher positionality, coding process, and saturation logic",
            "traceable excerpts or source evidence for each theme",
            "negative cases, triangulation, reflexivity, and an audit trail",
        ],
        "section_emphasis": ["context", "methodology", "findings", "reflexivity"],
        "plot_types": ["theme_map", "evidence_matrix", "case_comparison"],
    },
    "generic_empirical": {
        "keywords": (),
        "reporting_standards": ["domain-appropriate reporting checklist selected during review"],
        "required_evidence": [
            "explicit analysis unit, sampling, controls, endpoints, and exclusion rules",
            "effect estimates with uncertainty and provenance",
            "robustness, alternative explanations, and failure conditions",
        ],
        "section_emphasis": ["methods", "results", "robustness", "limitations"],
        "plot_types": ["interval_comparison", "sensitivity", "distribution"],
    },
}


REPORTING_GUIDES = {
    "CONSORT": "https://www.consort-statement.org/",
    "STROBE": "https://www.strobe-statement.org/",
    "TRIPOD": "https://www.tripod-statement.org/",
    "STARD": "https://www.equator-network.org/reporting-guidelines/stard/",
    "COREQ or SRQR where applicable": "https://www.equator-network.org/",
    "MIAME/MINSEQE": "https://www.fged.org/projects/miame/",
    "FAIR data principles": "https://www.go-fair.org/fair-principles/",
}


class PublicationStyleService:
    relative_path = Path("paper") / "PUBLICATION_STYLE.json"

    @staticmethod
    def context(project_path: str | Path, direction: str = "") -> str:
        root = Path(project_path).expanduser().resolve()
        parts = [str(direction or "")]
        for relative in (
            "ideas/SELECTED_IDEA.json",
            "ideas/ideas.md",
            "experiments/EXPERIMENT_PLAN.md",
            "experiments/configs/main.yaml",
            "literature/survey.md",
        ):
            path = root / relative
            if path.is_file():
                parts.append(path.read_text(encoding="utf-8", errors="replace")[:30000])
        return "\n".join(parts)

    @staticmethod
    def _scores(context: str, specs: dict[str, dict[str, Any]]) -> dict[str, int]:
        text = str(context or "").casefold()
        scores: dict[str, int] = {}
        for name, spec in specs.items():
            scores[name] = 0
            for keyword in spec.get("keywords", ()):
                pattern = (
                    r"(?<![a-z0-9])"
                    + re.escape(str(keyword).casefold())
                    + r"(?![a-z0-9])"
                )
                if re.search(pattern, text):
                    scores[name] += max(1, len(str(keyword).split()))
        return scores

    @classmethod
    def infer_family(cls, context: str, target_venue: str = "") -> str:
        venue = str(target_venue or "").casefold()
        ml_venues = ("iclr", "neurips", "nips", "icml", "cvpr", "eccv", "acl", "aaai")
        if any(item in venue for item in ml_venues):
            return "machine_learning"
        venue_families = (
            (
                "computer_systems",
                (
                    "sigcomm", "sosp", "osdi", "usenix", "sigmod", "vldb",
                    "icse", "chi", "computer and communications security",
                ),
            ),
            (
                "computational_biology",
                ("bioinformatics", "nature biotechnology", "nature genetics", "genome biology", "cell systems"),
            ),
            (
                "clinical_biomedical",
                ("jama", "lancet", "new england journal", "nejm", "bmj", "radiology"),
            ),
            (
                "experimental_natural_science",
                ("nature chemistry", "nature physics", "nature materials", "physical review", "acs"),
            ),
            (
                "engineering_systems",
                ("t-ro", "transactions on robotics", "automatica", "ieee robotics"),
            ),
            (
                "social_behavioral",
                ("american economic review", "aer", "psychological science"),
            ),
            (
                "theoretical_formal",
                ("stoc", "focs", "soda", "journal of the acm", "annals of mathematics"),
            ),
        )
        for family, markers in venue_families:
            if any(marker in venue for marker in markers):
                return family
        tie_priority = (
            "computational_biology",
            "clinical_biomedical",
            "computer_systems",
            "experimental_natural_science",
            "theoretical_formal",
            "qualitative_humanities",
            "social_behavioral",
            "engineering_systems",
            "machine_learning",
        )
        scores = cls._scores(context, FAMILY_SPECS)
        best = max(scores.values(), default=0)
        if best:
            return next(family for family in tie_priority if scores[family] == best)
        return "generic_quantitative"

    @classmethod
    def infer_study_archetype(cls, context: str, family: str) -> str:
        priority = (
            "intervention_trial",
            "diagnostic_prognostic",
            "omics_discovery",
            "formal_theory",
            "qualitative_mixed",
            "systems_testbed",
            "observational_cohort",
            "controlled_experiment",
            "simulation_modeling",
            "algorithm_benchmark",
        )
        scores = cls._scores(context, STUDY_ARCHETYPE_SPECS)
        best = max(scores.values(), default=0)
        if best:
            return next(name for name in priority if scores[name] == best)
        defaults = {
            "machine_learning": "algorithm_benchmark",
            "computer_systems": "systems_testbed",
            "computational_biology": "observational_cohort",
            "clinical_biomedical": "observational_cohort",
            "experimental_natural_science": "controlled_experiment",
            "social_behavioral": "observational_cohort",
            "engineering_systems": "systems_testbed",
            "theoretical_formal": "formal_theory",
            "qualitative_humanities": "qualitative_mixed",
        }
        return defaults.get(family, "generic_empirical")

    @staticmethod
    def implementation_family_for(
        research_family: str,
        study_archetype: str = "",
        context: str = "",
    ) -> str:
        """Map a publication family to an implementation discipline.

        The mapping is intentionally coarser than publication families: a
        clinical ML paper still becomes ``machine_learning`` when its content
        contains ML markers, while a protocol-only clinical paper remains an
        ``external_protocol`` project.  Simulation and systems work share the
        computational implementation path but retain their own evidence and
        visual contracts.
        """
        family = str(research_family or "generic_quantitative").casefold()
        archetype = str(study_archetype or "").casefold()
        context_text = str(context or "").casefold()
        if family != "theoretical_formal" and re.search(
            r"(?:machine learning|deep learning|neural network|transformer|pytorch|tensorflow|classifier|contrastive|embedding)",
            context_text,
        ):
            return "machine_learning"
        if archetype == "formal_theory" or family == "theoretical_formal":
            return "formal_verification"
        if archetype in {"intervention_trial", "observational_cohort", "diagnostic_prognostic", "qualitative_mixed"}:
            return "external_protocol"
        return IMPLEMENTATION_FAMILY_BY_RESEARCH_FAMILY.get(
            family,
            "computational_general",
        )

    @staticmethod
    def _venue_profile(target_venue: str) -> dict[str, Any]:
        venue = str(target_venue or "unspecified")
        lowered = venue.casefold()
        nature_like = any(
            token in lowered for token in ("nature", "science", "cell", "pnas")
        )
        computing_conference = any(
            token in lowered
            for token in (
                "iclr", "neurips", "icml", "cvpr", "acl", "aaai", "acm",
                "sig", "usenix", "sosp", "osdi", "chi", "icse",
            )
        )
        ieee_like = "ieee" in lowered or "transactions on" in lowered
        clinical_like = any(
            token in lowered for token in ("jama", "lancet", "nejm", "bmj")
        )
        if nature_like:
            name, font_size = "nature_family", 7.0
        elif computing_conference:
            name, font_size = "computing_conference", 8.0
        elif ieee_like:
            name, font_size = "ieee_journal", 8.0
        elif clinical_like:
            name, font_size = "clinical_journal", 8.0
        else:
            name, font_size = "generic_peer_review", 8.0
        return {
            "id": name,
            "venue": venue,
            "template_is_authoritative": True,
            "target_font_pt": font_size,
            "nature_like": nature_like,
            "computing_conference": computing_conference,
        }

    def build(
        self,
        *,
        context: str = "",
        target_venue: str = "",
        research_family: str = "",
        study_archetype: str = "",
    ) -> dict[str, Any]:
        family = (
            research_family
            if research_family in FAMILY_SPECS
            else self.infer_family(context, target_venue)
        )
        spec = FAMILY_SPECS[family]
        archetype = (
            study_archetype
            if study_archetype in STUDY_ARCHETYPE_SPECS
            else self.infer_study_archetype(context, family)
        )
        archetype_spec = STUDY_ARCHETYPE_SPECS[archetype]
        venue_profile = self._venue_profile(target_venue)
        venue = str(venue_profile["venue"])
        font_size = float(venue_profile["target_font_pt"])
        family_matches = ranked_matches(self._scores(context, FAMILY_SPECS))
        archetype_matches = ranked_matches(
            self._scores(context, STUDY_ARCHETYPE_SPECS)
        )
        standards = list(archetype_spec["reporting_standards"])
        reporting_urls = [
            REPORTING_GUIDES[name] for name in standards
            if name in REPORTING_GUIDES
        ]
        reference_guides = [FIELD_ADAPTIVE_VISUAL_GUIDE, *reporting_urls]
        if venue_profile["nature_like"]:
            reference_guides[1:1] = [
                NATURE_FIGURE_GUIDE_URL,
                NATURE_PANEL_GUIDE_URL,
            ]
        return style_payload(
            schema_version=STYLE_SCHEMA_VERSION,
            family=family,
            family_spec=spec,
            archetype=archetype,
            archetype_spec=archetype_spec,
            venue_profile=venue_profile,
            implementation_family=self.implementation_family_for(
                family, archetype, "" if research_family in FAMILY_SPECS else context
            ),
            family_matches=family_matches,
            archetype_matches=archetype_matches,
            family_overridden=research_family in FAMILY_SPECS,
            archetype_overridden=study_archetype in STUDY_ARCHETYPE_SPECS,
            evidence_contract=dict(
                DOMAIN_EVIDENCE_CONTRACTS.get(
                    family, DOMAIN_EVIDENCE_CONTRACTS["generic_quantitative"]
                )
            ),
            palette=ACCESSIBLE_PALETTE,
            reference_guides=reference_guides,
        )

    def prepare(
        self,
        project_path: str | Path,
        direction: str = "",
        *,
        target_venue: str = "",
        research_family: str = "",
        study_archetype: str = "",
    ) -> dict[str, Any]:
        root = Path(project_path).expanduser().resolve()
        payload = self.build(
            context=self.context(root, direction),
            target_venue=target_venue,
            research_family=research_family,
            study_archetype=study_archetype,
        )
        payload["generated_at"] = time.time()
        target = root / self.relative_path
        atomic_write_json(target, payload)
        return payload

    def load(self, project_path: str | Path) -> dict[str, Any]:
        target = Path(project_path).expanduser().resolve() / self.relative_path
        try:
            payload = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return payload if isinstance(payload, dict) else {}


publication_style_service = PublicationStyleService()
