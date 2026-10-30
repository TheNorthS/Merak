"""Domain evidence contracts used by publication-style classification."""

from __future__ import annotations

from typing import Any


DOMAIN_EVIDENCE_CONTRACTS: dict[str, dict[str, Any]] = {
    "machine_learning": {
        "analysis_unit": "independent sample, subject, session, or dataset group",
        "uncertainty": "multi-seed intervals with the split unit preserved",
        "statistics": ["mean and standard deviation", "confidence interval", "paired or grouped comparison"],
        "provenance": ["dataset and split manifest", "run/config identity", "metric definition", "checkpoint or prediction artifact"],
        "visual_priorities": ["matched main comparison", "component ablation", "robustness/error slices", "calibration or efficiency"],
    },
    "computer_systems": {
        "analysis_unit": "workload, request, trace, user task, or deployment run",
        "uncertainty": "repeated measurements with warm-up and tail quantiles",
        "statistics": ["median and percentile tail", "throughput/latency confidence interval", "matched workload comparison"],
        "provenance": ["hardware/software environment", "workload manifest", "run identity", "measurement script and raw logs"],
        "visual_priorities": ["scaling curve", "tail-latency distribution", "cost-quality frontier", "failure analysis"],
    },
    "computational_biology": {
        "analysis_unit": "sample, patient, cell, gene, variant, or independent cohort",
        "uncertainty": "cohort-aware intervals with batch and multiplicity handling",
        "statistics": ["effect size and confidence interval", "multiple-testing adjustment", "external-cohort sensitivity"],
        "provenance": ["sample/cohort manifest", "assay and preprocessing versions", "batch/QC record", "analysis and reference-data versions"],
        "visual_priorities": ["cohort/filtering flow", "effect/forest plot", "batch or cohort sensitivity", "pathway/biological validation"],
    },
    "clinical_biomedical": {
        "analysis_unit": "participant, encounter, episode, or prespecified clinical unit",
        "uncertainty": "prespecified confidence intervals and subgroup uncertainty",
        "statistics": ["effect estimate", "discrimination and calibration", "decision utility or survival endpoint"],
        "provenance": ["participant flow", "outcome/reference standard", "protocol and analysis-plan version", "external-validation identity"],
        "visual_priorities": ["participant flow", "subgroup forest", "calibration/decision curve", "survival or external validation"],
    },
    "experimental_natural_science": {
        "analysis_unit": "biological replicate, specimen, device, sample, or experimental run",
        "uncertainty": "replicate-level distributions with technical/biological distinction",
        "statistics": ["effect size and interval", "replicate distribution", "dose/time response or orthogonal validation"],
        "provenance": ["sample and condition registry", "instrument/acquisition settings", "replicate and exclusion log", "raw-data checksum"],
        "visual_priorities": ["replicate distribution", "dose/time response", "condition comparison", "orthogonal validation"],
    },
    "social_behavioral": {
        "analysis_unit": "participant, household, organization, region, or sampled case",
        "uncertainty": "cluster- or design-aware uncertainty with prespecified covariates",
        "statistics": ["estimate and confidence interval", "alternative specifications", "subgroup/heterogeneity analysis"],
        "provenance": ["sampling frame", "codebook and variable derivation", "missing-data treatment", "analysis-plan and model identity"],
        "visual_priorities": ["coefficient/forest plot", "marginal-effects plot", "specification sensitivity", "sampling/flow diagram"],
    },
    "engineering_systems": {
        "analysis_unit": "trial, trajectory, operating condition, workload, or hardware run",
        "uncertainty": "repeated-run intervals plus worst-case/failure accounting",
        "statistics": ["performance interval", "stress/failure rate", "latency, energy, or resource scaling"],
        "provenance": ["testbed and hardware registry", "controller/software version", "operating-condition manifest", "raw telemetry/log identity"],
        "visual_priorities": ["system architecture", "stress curve", "failure mode analysis", "resource scaling frontier"],
    },
    "theoretical_formal": {
        "analysis_unit": "definition, theorem, instance, proof obligation, or counterexample",
        "uncertainty": "not applicable; report exact conditions and boundary cases",
        "statistics": ["bound or rate", "assumption sensitivity", "counterexample/necessity check"],
        "provenance": ["notation and assumption registry", "proof dependency graph", "machine-checker/version", "counterexample artifact"],
        "visual_priorities": ["proof dependency map", "bound comparison", "phase diagram", "counterexample"],
    },
    "qualitative_humanities": {
        "analysis_unit": "participant, case, document, excerpt, event, or coded segment",
        "uncertainty": "not reduced to sampling error; report saturation, agreement, and reflexivity",
        "statistics": ["code/theme coverage", "negative-case accounting", "triangulation or agreement evidence"],
        "provenance": ["sampling rationale", "codebook/version", "excerpt-to-theme trace", "audit trail and reflexive memo"],
        "visual_priorities": ["case/corpus flow", "evidence matrix", "theme map", "negative-case comparison"],
    },
    "generic_quantitative": {
        "analysis_unit": "explicitly declared independent analysis unit",
        "uncertainty": "estimate uncertainty matched to the sampling or repeated-measure design",
        "statistics": ["effect estimate", "interval", "robustness or alternative explanation"],
        "provenance": ["data manifest", "analysis/config identity", "metric definition", "result artifact checksum"],
        "visual_priorities": ["design flow", "primary estimate", "sensitivity", "distribution or efficiency"],
    },
}
