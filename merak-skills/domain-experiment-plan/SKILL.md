---
name: domain-experiment-plan
allowed-tools: Read, Write, WritePart, AssembleDocument, Edit, Glob, Grep
artifact-outputs: ["experiments/EXPERIMENT_PLAN.md","experiments/METHOD_CONTRACT.json","experiments/RUN_SPEC.json","experiments/IMPLEMENTATION_BLUEPRINT.json"]
artifact-contracts: {"experiments/METHOD_CONTRACT.json": 2,"experiments/RUN_SPEC.json": 1,"experiments/IMPLEMENTATION_BLUEPRINT.json": 1}
description: Convert an accepted idea into a discipline-appropriate, executable evidence plan. Use for computational experiments, systems testbeds, simulations, clinical or observational protocols, omics studies, controlled laboratory work, formal proofs, and qualitative or mixed-methods research.
---

# Domain Experiment Plan

Own the canonical experiment-design artifacts named by the workflow.

## Incremental delivery

Persist one bounded artifact per model turn, then inspect the tool receipt before
continuing. Do not prepare all design files inside one response or spend a long
response describing what you will write. Use `WritePart` and `AssembleDocument`
for long Markdown/JSON documents when those tools are available; each part should
contain a bounded, coherent section. Keep the complete schema and scientific
content across parts. A staged part is not a delivered or accepted artifact.
For JSON split at object-member or array-element boundaries, never inside a
quoted string; assembly joins parts with whitespace and validates the complete
JSON and its versioned writer contract before replacing the canonical file.
After an interrupted response, inspect existing files and staged parts, then
continue the first incomplete artifact without rewriting completed material.

## Procedure

1. Read `paper/PUBLICATION_STYLE.json`, `ideas/SELECTED_IDEA.json`, the literature artifacts, and any reference implementation snapshot.
2. Map every accepted claim and mechanism to a discriminating observation, comparison, proof obligation, or source-evidence test. Include alternatives that could produce the same observation.
3. Freeze the unit of analysis, population/problem class, sampling or split rules, controls/comparators, endpoints, exclusion rules, uncertainty, multiplicity, missingness, sensitivity analyses, stopping rules, and provenance.
4. Write `experiments/EXPERIMENT_PLAN.md`, `experiments/METHOD_CONTRACT.json`, and `experiments/RUN_SPEC.json`. Preserve stable claim/mechanism IDs from the selected idea. `METHOD_CONTRACT.json` must use schema 2 and include an authored `scientific_scene` with public objects, provenance, and relations; schema 1 and compatibility rewrites are unsupported.
   For stochastic studies, declare the frozen execution seed list as top-level `RUN_SPEC.seeds` (a non-empty integer list), mirror the same values into the runner's configuration, and have the runner consume them. Do not replace execution seeds with augmentation/sampler seeds or change the frozen seed values to satisfy a validator. Deterministic/protocol studies must declare their implementation family rather than fabricate repetitions.
   Freeze publication evaluation facts as well: declare an explicit `scientific_outputs.primary_split` and `analysis_unit`, or independent `evaluation.holdout_axes` with their `data_requirements.manifest_paths`. Preserve every independent axis; do not merge them into one synthetic split. If multiple holdout axes are scheduled and a configuration selects an active axis, declare `data.active_holdout_axis` in `experiments/configs/main.yaml`, consistent with `evaluation.holdout_axes` and `data.split_manifests`. An active execution axis is not a claim that the other declared axes are optional. Declare `evaluation.primary_metric` and the configuration's `evaluation.analysis_unit_key` separately from prose claim statements. Do not fabricate a primary split, analysis unit, metric, comparator, or manifest merely to satisfy the figure producer.
   Evaluation protocol v1 requires `evaluation.protocol_schema: 1`, `holdout_axes: [subject, site, montage]` (a list of stable names), `primary_split` (the complete scientific evaluation scope), `primary_metric`, and `analysis_unit_key`. Axis manifest details belong in `data.split_manifests`, not inside holdout_axes. `data.active_holdout_axis` is execution selection only. Repeated RUN_SPEC/config declarations must agree.
   Multi-condition/axis studies require RUN_SPEC `scheduled_runs: {schema: 1, owner: scheduler, conditions: [...], holdout_axes: [...], output_root: experiments/results/cells}`. The scientific command binds `{condition}`, `{axis}`, `{seed}`, `{output_dir}` explicitly; the entrypoint must parse and use each argument. Every `outputs.per_run_files` path starts with `{output_dir}/`. Every cell writes independent artifacts; aggregate only after exact registered cell coverage is verified. Never claim implicit traversal from an unparameterized single-run command.
5. Use the execution mode appropriate to the archetype:
   - `computational`: provide runnable source/config, preflight, environment, seeds or repetitions, expected logs/results, resource limits, and anomaly-stop rules.
   - `external_protocol`: provide acquisition/collection protocol, case-report or measurement schema, QC, evidence-import manifest, and analysis contract. Set `gpu_required` false; do not fabricate a training command.
   - `formal_verification`: provide definitions, assumptions, theorem dependency graph, proof/checker commands if available, and counterexample tests. Set `gpu_required` false.
6. Create `experiments/src/` and `experiments/configs/` only with artifacts meaningful to the declared mode. A README or machine-readable protocol is valid for non-computational studies; do not add a fake neural network or `train.py`.
7. Mark unresolved data, recruitment, approvals, instrumentation, implementation, and external execution as pending. Planned or dry-run outputs are not evidence.

The plan must be falsifiable and auditable. Do not invent sample sizes, power, datasets, approvals, measurements, results, code execution, or proof completion.
