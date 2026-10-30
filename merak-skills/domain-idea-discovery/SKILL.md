---
name: domain-idea-discovery
allowed-tools: Read, Write, WritePart, AssembleDocument, Edit, Glob, Grep
artifact-outputs: ["ideas/ideas.md"]
description: Generate and rank falsifiable research ideas for any supported research family and study archetype. Use after literature synthesis when the workflow must avoid forcing clinical, biological, systems, theoretical, qualitative, or natural-science questions into a machine-learning template.
---

# Domain Idea Discovery

Create the canonical idea artifact requested by the workflow.

## Procedure

1. Read `paper/PUBLICATION_STYLE.json`, `literature/survey.md`, `literature/references.bib`, and any frozen reference-paper/code context.
2. Use the declared research family and study archetype. Infer neither a neural model nor an experiment type when the profile calls for a cohort, intervention, assay, simulation, theorem, systems testbed, causal design, or qualitative study.
3. Generate a compact candidate set. For each candidate state the research question, proposed mechanism or explanatory construct, nearest alternatives, minimum decisive evidence, falsification condition, feasibility blockers, and ethical or governance constraints.
4. Rank candidates by scientific importance, identifiable novelty, discriminating evidence, feasibility, and fit to the target venue. Penalize ideas whose apparent novelty is only a renamed component or whose evidence cannot distinguish the mechanism from a simpler explanation.
5. Select a recommended Top-1 without asking the researcher to choose unless the workflow explicitly enabled a human checkpoint.

## Archetype rules

- Algorithm benchmark: require strong and compute-matched controls, leakage-safe splits, uncertainty, ablations, robustness, and resource accounting.
- Observational or causal study: define population, exposure, outcome, estimand, identification assumptions, confounders, negative controls, and sensitivity analysis.
- Diagnostic or prognostic study: define target population, index method, reference standard, timing, calibration, utility, and external validation.
- Intervention trial: define intervention, comparator, allocation, endpoints, harms, and analysis population.
- Omics discovery: define sample provenance, assay QC, batch handling, multiplicity, and independent or orthogonal validation.
- Controlled natural-science experiment: define biological versus technical replicates, controls, perturbations, measurements, and orthogonal validation.
- Systems or engineering testbed: define system boundary, workloads, scale, failures, repeated measurements, and cost-quality trade-offs.
- Simulation: define governing assumptions, verification, validation, convergence, sensitivity, and uncertainty propagation.
- Formal theory: define objects, assumptions, theorem target, proof obligations, and counterexamples.
- Qualitative or mixed methods: define sampling rationale, corpus or participants, coding/interpretation procedure, reflexivity, negative cases, and triangulation.

Do not invent citations, datasets, approvals, sample sizes, measurements, results, or implementation status.
