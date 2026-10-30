"""Cross-domain staged implementation topology."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ImplementationStage:
    id: str
    title: str
    targets: tuple[str, ...]
    purpose: str


ML_STAGES = (
    ImplementationStage(
        "data",
        "Data contract and split-safe loading",
        (
            "experiments/src/data.py",
            "experiments/src/data_contract.py",
        ),
        "Implement configured data ingestion, analysis-unit identities, isolated splits, batching, and leakage checks.",
    ),
    ImplementationStage(
        "method",
        "Accepted mechanisms and model",
        (
            "experiments/src/models.py",
            "experiments/src/objectives.py",
        ),
        "Implement every frozen mechanism, the model forward path, objectives, task heads, and declared ablation switches.",
    ),
    ImplementationStage(
        "training",
        "Training and optimization",
        ("experiments/src/train.py",),
        "Integrate data and method code into the real entrypoint with iteration, loss, gradient updates, checkpoint selection, and anomaly handling.",
    ),
    ImplementationStage(
        "evaluation",
        "Evaluation, statistics, and provenance",
        (
            "experiments/src/metrics.py",
            "experiments/src/evaluation.py",
            "experiments/src/provenance.py",
        ),
        "Implement inference, registered metrics, per-unit outputs, uncertainty inputs, result persistence, and provenance binding.",
    ),
    ImplementationStage(
        "integration",
        "Executable integration contract",
        (
            "experiments/src/test_pipeline.py",
            "experiments/IMPLEMENTATION_EVIDENCE_PATCH.json",
            "experiments/RUN_SPEC.json",
            "experiments/configs/main.yaml",
        ),
        "Wire the complete execution path, add bounded tests, and finalize truthful method/run contracts only after all mechanisms are reachable.",
    ),
)

COMPUTATIONAL_STAGES = (
    ImplementationStage(
        "data",
        "Data, parameters, and analysis-unit contract",
        ("experiments/src/data.py", "experiments/src/data_contract.py"),
        "Implement configured inputs, units, partitions or scenarios, validation, and leakage/contamination controls.",
    ),
    ImplementationStage(
        "method",
        "Algorithms, mechanisms, and numerical method",
        ("experiments/src/algorithms.py", "experiments/src/simulation.py"),
        "Implement every frozen mechanism, algorithmic stage, numerical assumption, comparator switch, and sensitivity factor.",
    ),
    ImplementationStage(
        "training",
        "Scientific execution and orchestration",
        ("experiments/src/run_analysis.py",),
        "Integrate inputs and method code into the real scientific entrypoint with iteration, deterministic configuration, failure handling, and bounded execution.",
    ),
    ImplementationStage(
        "evaluation",
        "Evaluation, statistics, and provenance",
        (
            "experiments/src/metrics.py",
            "experiments/src/evaluation.py",
            "experiments/src/provenance.py",
        ),
        "Implement registered estimands or metrics, uncertainty, robustness checks, result persistence, and provenance binding.",
    ),
    ML_STAGES[-1],
)

PROTOCOL_STAGES = (
    ImplementationStage(
        "data",
        "Protocol population, sampling, and data contract",
        ("experiments/src/protocol.py", "experiments/src/data_contract.py"),
        "Encode eligibility, sampling or recruitment, consent/access constraints, analysis units, quality control, and missing-data rules.",
    ),
    ImplementationStage(
        "method",
        "Estimands and domain analysis",
        ("experiments/src/analysis.py", "experiments/src/estimands.py"),
        "Implement declared outcomes, estimands, adjustment or coding procedures, controls, and sensitivity specifications.",
    ),
    ImplementationStage(
        "training",
        "Protocol execution and analysis driver",
        ("experiments/src/run_analysis.py",),
        "Integrate protocol checks and the executable analysis path without inventing unavailable observations or physical procedures.",
    ),
    ImplementationStage(
        "evaluation",
        "Inference, validation, and provenance",
        (
            "experiments/src/metrics.py",
            "experiments/src/evaluation.py",
            "experiments/src/provenance.py",
        ),
        "Implement effects or themes, uncertainty, subgroup/negative-case checks, external validation, result persistence, and provenance.",
    ),
    ML_STAGES[-1],
)

FORMAL_STAGES = (
    ImplementationStage(
        "data",
        "Definitions, assumptions, and problem instances",
        ("experiments/src/definitions.py", "experiments/src/instances.py"),
        "Encode the formal domain, assumptions, constraints, admissible instances, and boundary cases.",
    ),
    ImplementationStage(
        "method",
        "Theorems, constructions, and checker logic",
        ("experiments/src/theorems.py", "experiments/src/checker.py"),
        "Implement declared lemmas, constructions, invariants, proof obligations, and machine-checkable conditions.",
    ),
    ImplementationStage(
        "training",
        "Verification and counterexample search",
        ("experiments/src/verify.py",),
        "Integrate proof checks, bounded verification, boundary cases, and counterexample search in the real entrypoint.",
    ),
    ImplementationStage(
        "evaluation",
        "Bounds, counterexamples, and provenance",
        (
            "experiments/src/validation.py",
            "experiments/src/counterexamples.py",
            "experiments/src/provenance.py",
        ),
        "Persist verified statements, bounds, counterexamples, complexity facts, and source/proof provenance.",
    ),
    ML_STAGES[-1],
)


