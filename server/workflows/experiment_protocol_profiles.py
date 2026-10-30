"""Domain-specific protocol guidance derived from declared study families."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ProtocolProfile:
    protocol_title: str
    protocol_lines: list[str]
    independence_lines: list[str]
    default_controls: list[str]
    fairness_line: str
    mechanism_interpretation: str
    analysis_lines: list[str]
    reproducibility_lines: list[str]
    resource_lines: list[str]


def resolve_protocol(
    implementation_family: str,
    research_family: str,
    study_archetype: str,
    seeds: list[str],
) -> ProtocolProfile:
    if implementation_family == "machine_learning":
        return machine_learning(seeds)
    if implementation_family == "formal_verification":
        return formal_verification(seeds)
    if implementation_family == "external_protocol":
        if (
            "qualitative" in research_family
            or "qualitative" in study_archetype
            or "interview" in study_archetype
        ):
            return qualitative(seeds)
        return external_protocol(seeds)
    return computational_general(seeds)


def machine_learning(seeds: list[str]) -> ProtocolProfile:
    protocol_title = "Dataset, Analysis Unit, and Split Protocol"
    protocol_lines = [
        "- Record dataset identities, licenses, versions, preprocessing hashes, inclusion/exclusion rules, labels, and the independent analysis unit before execution.",
        "- Use a group/subject/temporal or other domain-valid independent split; freeze test data before model selection and fit preprocessing/calibration on training/validation data only.",
        "- Preserve stable unit IDs and content hashes so duplicates, derived views, and fitted-state leakage can be detected across partitions.",
    ]
    independence_lines = [
        "- Fail preflight when raw identities, derived duplicates, augmented views, labels, or fitted preprocessing state cross forbidden split boundaries.",
        "- Pair repeated runs on the same locked split and never treat correlated observations as independent replicates.",
        "- Persist split, preprocessing, source, configuration, checkpoint, and environment hashes for every accepted run.",
    ]
    default_controls = [
        "nearest verified prior method",
        "simple task-appropriate baseline",
        "capacity- and optimization-opportunity-matched control",
    ]
    fairness_line = "- Match data, split, tuning opportunity, stopping rule, update budget, and capacity; disclose every residual mismatch."
    mechanism_interpretation = "Hold data, split, seed, optimization opportunity, and capacity fixed where scientifically possible."
    analysis_lines = [
        f"- Declared seeds: {(', '.join(seeds) if seeds else 'fix before execution and justify by power/resource analysis')}.",
        "- Report point estimates, dispersion, confidence intervals, and paired effect sizes using the true independent unit.",
        "- Predeclare primary metric, decision margin, multiplicity family, missing/failed-run policy, calibration and subgroup analyses where applicable.",
        "- Register each unordered model pair exactly once; never count A-vs-B and B-vs-A as separate hypotheses or reversals.",
    ]
    reproducibility_lines = [
        "- Persist replicate seed, resolved config, source snapshot, data/split/preprocessing hashes, dependency versions, hardware, command, checkpoint hash, and timestamps.",
        "- Keep attempts isolated; aggregate only successful, runtime-owned artifacts and retain failures separately.",
    ]
    resource_lines = [
        "- G0: syntax/config checks and one-batch CPU/device sanity run; no scientific claim.",
        "- G1: bounded pilot; stop on leakage, NaN/Inf, loss collapse, OOM, divergence, or stalled logs.",
        "- G2: locked main controls and mechanism tests; G3: multi-run, shift, subgroup, calibration, and resource analysis.",
        "- Record accelerator/CPU type, peak memory, wall time, energy/cost where available, and retry policy.",
    ]
    return ProtocolProfile(
        protocol_title=protocol_title,
        protocol_lines=protocol_lines,
        independence_lines=independence_lines,
        default_controls=default_controls,
        fairness_line=fairness_line,
        mechanism_interpretation=mechanism_interpretation,
        analysis_lines=analysis_lines,
        reproducibility_lines=reproducibility_lines,
        resource_lines=resource_lines,
    )


def formal_verification(seeds: list[str]) -> ProtocolProfile:
    protocol_title = "Formal Domain, Assumptions, and Instance Protocol"
    protocol_lines = [
        "- Freeze definitions, assumptions, admissibility constraints, theorem scope, and the exact statement of every proof obligation.",
        "- Register canonical, boundary, degenerate, and adversarial instances before evaluating the accepted construction.",
        "- Version every axiom set, solver/checker configuration, external lemma, and generated certificate.",
    ]
    independence_lines = [
        "- Separate assumptions from derived statements and fail verification when an obligation is only asserted, circular, or checked outside its declared domain.",
        "- Search counterexamples independently of the constructive path where possible and record unsearched regions as explicit scope limits.",
        "- Bind each verdict to checker build, proof source, instance registry, solver options, timeout, and certificate hashes.",
    ]
    default_controls = [
        "strongest relevant known bound or construction",
        "simpler admissible construction",
        "relaxed/tightened assumption reference",
    ]
    fairness_line = "- Compare statements under identical definitions and assumptions; tabulate any scope, oracle, precision, or complexity mismatch."
    mechanism_interpretation = "Hold definitions and assumptions fixed; isolate the lemma, invariant, construction step, or assumption whose necessity is tested."
    analysis_lines = [
        "- Report obligation status, guarantee/bound, counterexamples, checker coverage, numerical tolerance if any, and proof/checker complexity.",
        "- Distinguish proved, machine-checked, bounded-tested, falsified, timed-out, and unverified statements; never convert bounded search into a universal proof.",
        "- Predeclare timeout/memory limits, admissible instance range, solver nondeterminism policy, and treatment of unknown results.",
    ]
    reproducibility_lines = [
        "- Persist assumption-registry, theorem-source, checker-build, dependency, solver-option, instance-set, certificate, and result hashes.",
        "- Retain failed obligations, counterexamples, timeouts, and minimized witnesses without mixing them into verified aggregates.",
    ]
    resource_lines = [
        "- G0: parse/type/checker configuration validation on canonical toy instances; no theorem claim.",
        "- G1: bounded obligations and counterexample search; G2: full registered instance/obligation suite; G3: boundary, scaling, and alternative-assumption analysis.",
        "- Record solver/checker versions, CPU/accelerator, precision, memory, wall time, timeouts, and search coverage.",
    ]
    return ProtocolProfile(
        protocol_title=protocol_title,
        protocol_lines=protocol_lines,
        independence_lines=independence_lines,
        default_controls=default_controls,
        fairness_line=fairness_line,
        mechanism_interpretation=mechanism_interpretation,
        analysis_lines=analysis_lines,
        reproducibility_lines=reproducibility_lines,
        resource_lines=resource_lines,
    )


def qualitative(seeds: list[str]) -> ProtocolProfile:
    protocol_title = "Sampling, Corpus, and Coding Protocol"
    protocol_lines = [
        "- Freeze the population/corpus, purposive or theoretical sampling logic, inclusion/exclusion rules, access/consent constraints, and unit of analysis.",
        "- Version the interview guide, field protocol, codebook, transcription/redaction rules, and stopping/saturation criteria.",
        "- Preserve case and excerpt identities in a privacy-safe ledger so theme provenance and negative cases remain auditable.",
    ]
    independence_lines = [
        "- Separate recruitment, coding, adjudication, and interpretation roles where feasible; disclose positionality and dependency risks.",
        "- Use double-coding/adjudication or documented peer debriefing for contested categories and actively search for disconfirming cases.",
        "- Bind themes to corpus snapshot, codebook version, coder/adjudication ledger, saturation assessment, and excerpt provenance.",
    ]
    default_controls = [
        "alternative coding framework",
        "independent coder or adjudicated interpretation",
        "negative/disconfirming case set",
    ]
    fairness_line = "- Apply comparison frameworks to the same eligible corpus and disclose coder access, prompting, iteration, and adjudication differences."
    mechanism_interpretation = "Hold corpus and coding opportunity fixed; isolate the codebook rule, sampling choice, triangulation source, or interpretive mechanism."
    analysis_lines = [
        "- Report theme prevalence only with a defensible denominator; emphasize meaning, variation, rival explanations, and negative cases rather than pseudo-significance.",
        "- Predeclare saturation logic, triangulation sources, coder agreement/adjudication procedure, reflexivity, and treatment of ambiguous excerpts.",
        "- Preserve quotations/excerpts and case context subject to consent, privacy, and redaction constraints.",
    ]
    reproducibility_lines = [
        "- Persist corpus snapshot, sampling ledger, protocol and codebook versions, coding decisions, adjudication history, saturation memo, and analysis environment.",
        "- Retain excluded/ambiguous/negative cases and rationale; never silently rewrite the codebook after seeing the conclusion.",
    ]
    resource_lines = [
        "- G0: protocol/codebook pilot and privacy/access validation; no substantive claim.",
        "- G1: bounded pilot coding and codebook refinement; G2: frozen main coding; G3: negative-case, triangulation, saturation, and transferability audit.",
        "- Record researcher/coder time, corpus volume, adjudication load, tool/model versions if used, and privacy constraints.",
    ]
    return ProtocolProfile(
        protocol_title=protocol_title,
        protocol_lines=protocol_lines,
        independence_lines=independence_lines,
        default_controls=default_controls,
        fairness_line=fairness_line,
        mechanism_interpretation=mechanism_interpretation,
        analysis_lines=analysis_lines,
        reproducibility_lines=reproducibility_lines,
        resource_lines=resource_lines,
    )


def external_protocol(seeds: list[str]) -> ProtocolProfile:
    protocol_title = "Population, Protocol, and Estimand Contract"
    protocol_lines = [
        "- Freeze population/source, eligibility, recruitment or sampling, exposure/intervention, outcomes/estimands, sites, time windows, and independent analysis unit.",
        "- Version acquisition/assay/annotation procedures, quality control, missingness rules, exclusion decisions, and preregistered analysis.",
        "- Preserve participant/sample/site/batch/corpus identities in a privacy-safe provenance ledger.",
    ]
    independence_lines = [
        "- Audit selection bias, confounding, immortal-time/information leakage, site/batch effects, outcome ascertainment, and correlated units as applicable.",
        "- Fit imputation, normalization, adjustment, and threshold choices without using protected outcome/test information.",
        "- Bind estimates to cohort/protocol/registry, site/batch/corpus snapshot, analysis-code, and decision-ledger identities.",
    ]
    default_controls = [
        "domain-standard reference or usual-practice condition",
        "unadjusted and prespecified adjusted analysis",
        "negative control or alternative plausible specification",
    ]
    fairness_line = "- Compare on identical eligibility, follow-up, outcome definition, analysis unit, and available information; disclose residual confounding or protocol mismatch."
    mechanism_interpretation = "Hold population/protocol fixed; isolate the exposure, adjustment, assay/procedure step, or causal/measurement mechanism."
    analysis_lines = [
        "- Report estimand-aligned effects, uncertainty, missingness, site/subgroup heterogeneity, multiplicity, and sensitivity to unmeasured bias where applicable.",
        "- Predeclare decision thresholds, adjustment set, censoring/missing-data handling, exclusion policy, and failed acquisition/batch handling.",
        "- Distinguish confirmatory, exploratory, feasibility, and externally validated analyses.",
    ]
    reproducibility_lines = [
        "- Persist protocol/registry, cohort/corpus snapshot, site/batch/assay, analysis-code/configuration, environment, and result hashes plus the decision ledger.",
        "- Retain exclusions, missing/failed observations, deviations, and adverse/negative outcomes separately from accepted aggregates.",
    ]
    resource_lines = [
        "- G0: protocol/schema/eligibility and data-quality validation; no outcome claim.",
        "- G1: feasibility or pilot analysis; G2: locked primary estimand; G3: sensitivity, subgroup/site/batch, negative-control, and external-validation analysis.",
        "- Record sample/corpus acquisition, assay/annotation/compute costs, analyst time, deviations, and resource limits.",
    ]
    return ProtocolProfile(
        protocol_title=protocol_title,
        protocol_lines=protocol_lines,
        independence_lines=independence_lines,
        default_controls=default_controls,
        fairness_line=fairness_line,
        mechanism_interpretation=mechanism_interpretation,
        analysis_lines=analysis_lines,
        reproducibility_lines=reproducibility_lines,
        resource_lines=resource_lines,
    )


def computational_general(seeds: list[str]) -> ProtocolProfile:
    protocol_title = "Inputs, Parameters, Scenarios, and Analysis Units"
    protocol_lines = [
        "- Freeze input identities/versions, admissible parameter ranges, initial/boundary conditions, scenario registry, units, precision, and independent analysis unit.",
        "- Version preprocessing, numerical method, discretization, stopping criteria, reference solutions, and exclusion/failure rules.",
        "- Preserve scenario/instance IDs and hashes so every result can be reproduced from the resolved configuration.",
    ]
    independence_lines = [
        "- Separate calibration/tuning scenarios from decisive evaluation and audit duplicated or derived instances across partitions.",
        "- Test discretization, tolerance, initialization, stochasticity, parameter identifiability, and numerical stability rather than treating repeat runs as independent evidence.",
        "- Bind outputs to input, parameter-grid, algorithm-source, environment, precision, and runtime identities.",
    ]
    default_controls = [
        "strongest verified reference algorithm/model",
        "simple domain-valid reference condition",
        "mechanism-disabled or assumption-matched alternative",
    ]
    fairness_line = "- Match inputs, admissible ranges, precision, stopping rule, initialization opportunity, and resource budget; disclose every residual mismatch."
    mechanism_interpretation = "Hold inputs, ranges, precision, and resource opportunity fixed while isolating the algorithmic mechanism or assumption."
    analysis_lines = [
        f"- Declared stochastic replicates: {(', '.join(seeds) if seeds else 'none unless the method is stochastic; then freeze and justify them before execution')}.",
        "- Report primary estimands/metrics, uncertainty where stochastic, numerical error, stability, sensitivity, boundary failures, and resource scaling.",
        "- Predeclare decision criteria, parameter grid, tolerance/precision, multiplicity if inferential comparisons are made, and failed-run handling.",
    ]
    reproducibility_lines = [
        "- Persist input/scenario, parameter-grid, source, dependency, environment, precision, command, replicate, output, and runtime hashes.",
        "- Keep attempts isolated and retain divergence, timeout, infeasible, and boundary failures without mixing them into accepted aggregates.",
    ]
    resource_lines = [
        "- G0: syntax/config/unit and toy-instance validation; no scientific claim.",
        "- G1: bounded pilot across representative scenarios; G2: locked main comparison and necessity tests; G3: sensitivity, boundary, stability, and scaling analysis.",
        "- Record CPU/accelerator, precision, peak memory, wall time, energy/cost where available, timeout, and retry policy.",
    ]
    return ProtocolProfile(
        protocol_title=protocol_title,
        protocol_lines=protocol_lines,
        independence_lines=independence_lines,
        default_controls=default_controls,
        fairness_line=fairness_line,
        mechanism_interpretation=mechanism_interpretation,
        analysis_lines=analysis_lines,
        reproducibility_lines=reproducibility_lines,
        resource_lines=resource_lines,
    )
