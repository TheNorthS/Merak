# Research Quality Workflow

MERAK treats a paper as the final report of a traceable research process, not as
the primary output. The workflow can run from a research question or from a
user-supplied reference paper and codebase.

## Skill Execution Semantics

Workflow skills define stage contracts. Model-owned stages load the selected
owner or specialist `SKILL.md`; staged implementation and writing may use
multiple bounded sessions. Deterministic stages use runtime services instead
of claiming model execution. A listed skill is not executed until its actual
invocation starts. Invocations bind the complete policy, tool allowlist,
project root and permitted outputs, with traces under `.merak/skill-invocations/`.

The workflow records owner lifecycle state under
`.merak/runs/<run_id>.skills.json`. A skill is reported as completed only
after its session returns successfully; merely copying or compacting its policy
does not count as execution. Validators remain independent and cannot inherit
the author's hidden stylistic context.

Chat and workflow agents use separate sessions and path policies. Chat is
restricted to user-facing research artifacts and stages file changes for
approval. Workflow sessions may discover files anywhere inside the canonical
research project, but writes remain subject to node and invocation ownership.
Runtime-owned acceptance, provenance and execution state cannot be authored by
the model. The immutable `.merak/reference_context/` snapshot stays read-only.
Workflow tool errors never use Chat-specific policy messages.

For paper production, the default order is narrative -> executed
`paper-plan` delegate -> figures -> executed `paper-write` owner -> review
-> audit -> compile. The planning delegate must write
`paper/PAPER_PLAN.md`; figures and manuscript prose consume that artifact.

## Research Modes

### From Research Question

The workflow retrieves literature, proposes and screens ideas, designs and runs
experiments, analyzes machine-readable results, generates persistent figures,
and writes and reviews the paper. When **Run experiment** is enabled, downstream
result, figure, and paper gates require metrics whose hashes are owned by a
successful runtime tool event. A model-written metrics file alone is rejected.

When experiment execution is disabled, the user selects one evidence mode:

- `design_only`: method, study design, replacement schemas, and no quantitative conclusion;
- `synthetic_preview`: deterministic scenario values for exercising analysis,
  figures and writing. Seven evidence roles are maintained; the contribution
  selects which figures and tables appear in the manuscript. This is not proof
  that the proposed method and baselines were trained or evaluated. The text
  must explain the construction and inference limits, with a final Simulation
  Study Disclosure after the conclusion and before the bibliography. Detailed
  provenance and submission eligibility are also recorded in sidecars;
- `existing_results`: prior metrics accepted only when a successful runtime event
  owns their current hashes;
- `secondary_analysis`: public results accepted through
  `experiments/results/SECONDARY_EVIDENCE.json`.

Each secondary source entry must contain `data_path`, `sha256`, `source_url` or
`doi`, and a `citation_key` present in `literature/references.bib`. A missing or
mismatched field blocks the evidence upgrade. Design and synthetic modes always
set `submission_eligible=false` in sidecar state.

## Idea-to-Implementation Contracts

Scientific alignment is contract-driven and domain-neutral. The novelty stage
writes `ideas/SELECTED_IDEA.json` with the accepted title, claims, mechanisms,
and falsification conditions. The experiment-design stage writes
`experiments/METHOD_CONTRACT.json`, mapping those immutable claim and mechanism
IDs to project-relative code symbols, non-comment source anchors, structured
configuration keys, tests, outcomes, controls, and failure conditions.

MERAK validates the declared mappings against the actual files and pins the
method contract to the accepted idea artifact by SHA256. It does not assume a
particular architecture, objective, dataset, task, programming language, or
scientific field. A CNN, analytical solver, controller, or any other method may
be the proposed method when the accepted idea declares it. Conversely, any
convenient substitute is rejected when it does not implement the accepted
mechanism contract. Adding domain keywords to the gate is not an accepted way
to repair alignment failures.

### Reference Paper + Code Innovation

This mode requires a local PDF/TeX paper and a local checked-out code directory.
MERAK creates a project-local immutable snapshot under
`.merak/reference_context/snapshots/<snapshot_id>/`. Secrets, generated files,
dependencies, checkpoints, and large binary files are excluded.

The workflow must produce `ideas/INNOVATION_BRIEF.md` with:

- reference paper claims;
- behavior observed in the reference code;
- paper-code gaps;
- the novelty delta and nearest neighbors;
- the proposed method;
- reference baseline reproduction;
- falsification tests and ablations;
- a claim-to-evidence map.

The brief and both experiment configs must name the active reference snapshot.
Executed innovation runs use these canonical paths:

```text
experiments/configs/reference_baseline.yaml
experiments/configs/proposed_method.yaml
experiments/results/reference_baseline/metrics.json
experiments/results/proposed_method/metrics.json
```

The runtime records successful commands, timestamps, config hashes, and result
artifact hashes in `.merak/execution_events.jsonl`. If the supplied baseline is
not reproduced under matched conditions, downstream gates block superiority
claims instead of silently turning a plan into a result.

## Paper Length

The UI accepts an approximate target and page tolerance. MERAK writes the
resolved soft page budget to `paper/PAPER_BUDGET.json`, injects section and word budgets
into writing and review prompts, compiles the actual PDF, and records the result
in `paper/PAPER_BUILD.json`.

If the compiled page count is outside the accepted range, MERAK runs at most two
reversible revisions. Expansion may add grounded method details, controls,
protocols, evidence analysis, or limitations. Compression may remove repetition.
Margins, font sizes, figure scaling, fabricated empirical claims, and filler are
not accepted ways to satisfy the target. Page count is a soft planning target:
the measured deviation is retained as a warning and does not invalidate an
otherwise sound manuscript.

## Manuscript Asset Boundary

Internal claim, mechanism, falsification, and implementation IDs remain in
`SELECTED_IDEA.json`, method contracts, and `.merak/research_audit/`. They must
not appear as `C1`, `M1`, or similar labels in manuscript prose, figures, tables,
or slides. Claim maps, execution status, gate decisions, and falsification trees
are internal research controls, not default paper figures.

`paper/tables/TABLE_MANIFEST.json` contains domain-facing study-design, method,
and provenance-backed result tables only. `figures/FIGURE_MANIFEST.json` keeps
all IDE-preview assets. Administrative and placeholder entries are excluded;
eligible synthetic-preview figures may be selected for a disclosed draft but
do not establish empirical evidence or submission readiness. Method figures are validated
against domain-facing mechanism terms from the selected idea and structured run
specification rather than against visible internal IDs.

## Failure Recovery

Authors write bounded chapter candidates. Validators inspect the same candidate
file view before publishing to canonical manuscript paths. Missing or rejected
content remains unresolved; a model's completion message does not replace files
or evidence. Deterministic services assemble validated chapters, bind assets and
compile presentation copies; they do not prove research conclusions or replace
missing experiments. Recovery revalidates saved candidates and accepted outputs
against their current dependencies before requesting another model attempt.
