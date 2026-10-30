# MERAK Engineering Standards

These rules apply to all new code and every touched module. They are acceptance
criteria, not suggestions.

## 1. Module size and responsibility

- A production source file should stay below 500 physical lines and must stay
  below 800 lines.
- A test file should stay below 800 lines and must stay below 1,200 lines.
- One class owns one cohesive responsibility. A class should stay below 300
  lines and must stay below 500 lines.
- A function should stay below 50 lines and must stay below 80 lines, excluding
  a short declarative data table.
- Do not add another responsibility to an oversized module. Extract a named
  service first.
- Existing size debt is recorded in `docs/code-size-baseline.json`. A debt file
  may only shrink. New exceptions are prohibited.

Preferred backend boundaries:

```text
API route -> application service -> domain service -> repository/adapter
                                      |
                                      -> pure validators and policies
```

Workflow orchestration coordinates services; it must not contain renderer,
LaTeX, statistics, persistence, model-provider, or domain-policy implementations.

Preferred frontend boundaries:

```text
page shell -> feature sections -> focused components
           -> feature hooks -> store/API adapters
```

A React component should not combine persistence, API polling, workflow policy,
form normalization, and presentation.

## 2. Production code, not demo code

- No placeholder values, fake success, `TODO` behavior, silent `pass`, or
  `NotImplementedError` may exist on an enabled production path.
- A scaffold must be typed and explicitly non-executable. It cannot satisfy a
  production artifact or quality gate.
- Do not catch `Exception` merely to continue. Translate a known failure into a
  typed domain error or re-raise it with operation and artifact context.
- Do not duplicate business rules in prompts. Deterministic ownership,
  validation, hashes, state transitions, and routing belong in code.
- Persisted artifacts use schema versions, atomic writes, stable identifiers,
  and content hashes where downstream correctness depends on identity.
- Public manuscript/figure text is separate from machine field names. Stable
  schema keys may use snake case; visible scientific labels may not expose it.
- Phase-2b figures use typed `publication_labels` (`concept`, `math`, or
  `metric`). Mathematical notation requires an explicit publication rendering;
  source symbols and paths remain invisible provenance. Untyped `visible_terms`
  are unsupported.
- Every semantic figure declares exactly one `producer_kind`. A model must not
  edit deterministic source output; mixed repairs are partitioned by producer.
- Figure candidates are rendered and scientifically validated inside a bounded
  transaction. Source, variants, and manifest commit together or the canonical
  artifact is restored.

## 3. Workflow state rules

- Every node has one artifact owner and one validator owner.
- A repair routes to the producer of the failing artifact, never to a consumer
  that can only delete or bypass it.
- During an unfinished run, upstream semantic changes invalidate only declared
  downstream dependencies. Completed runs are immutable historical deliveries:
  sidebar edits create separate local revisions, preserve original artifacts,
  and never schedule or invalidate nodes. Only an explicit user action starts
  further workflow execution.
- Runtime-owned fields such as hashes, lifecycle status, timestamps, leases,
  and renderer provenance are never delegated to a language model.
- A revision must record target files, semantic asset IDs, before/after
  fingerprints, structured findings, and the fresh gate result.
- No-progress detection compares the finding set and the implicated semantic
  artifacts. A fresh passing gate is valid even when bytes did not change.
- Byte changes with zero resolved finding IDs are `ineffective_content_change`,
  not progress. Logs must name overwrite, ineffective edit, and producer/gate
  contract conflict as diagnostic possibilities.

## 4. Experiment safety and authorization

Verification levels are explicit:

- **V0 — static:** parse, import graph, type checking, schema inspection, and
  deterministic reasoning. Always allowed for implementation work.
- **V1 — pure/local:** focused tests of pure functions using temporary fixtures;
  no workflow, training, network dataset, GPU, remote host, or paid service.
- **V2 — integration:** start local services or resume a workflow. Requires an
  explicit user request to run or verify that workflow.
- **V3 — scientific execution:** training, inference over research data, remote
  execution, GPU jobs, experiment schedulers, or paid compute. Requires an
  explicit user command for the exact experiment scope.

Without a V2/V3 instruction, use V0 and narrowly scoped V1 checks only. Never
infer permission to run a real experiment from a request to review or repair
code. Simulation generation is also execution and must be requested when it
changes project artifacts.

## 5. Verification contract

Every change records:

1. the invariant being repaired;
2. the owning module;
3. the smallest deterministic check that proves the invariant;
4. the commands actually run;
5. checks deliberately not run and why.

Prefer one regression test per defect. Do not use an end-to-end workflow as the
first diagnostic tool. Full-suite, full-workflow, training, and remote tests are
never the default.

## 6. Naming and readability

- Python: four spaces, type annotations on public boundaries, snake case
  modules/functions, PascalCase classes, explicit return types.
- TypeScript: two spaces, strict types at API/store boundaries, PascalCase React
  components, `useSomething` hooks, no new `any` without a documented adapter
  boundary.
- Prefer domain names such as `FigureArtifactRegistry` or
  `RevisionCheckpointPolicy` over `Manager`, `Helper`, or `Utils`.
- Comments explain an invariant or trade-off, not the syntax below them.
- Functions return typed result objects for multi-field outcomes instead of
  loosely shaped dictionaries when the contract is stable.

## 7. Change acceptance

A change is incomplete when it:

- grows an oversized file;
- introduces a new size exception;
- leaves a placeholder on a reachable path;
- mixes runtime-owned metadata with model-authored content;
- bypasses a failing artifact instead of repairing its producer;
- reports completion without a proportional V0/V1 verification result.

Run `npm run check:standards` before handoff. Strict size checking is the default;
the empty baseline is not permission to add new exceptions.

Maintain one current implementation of each contract. Do not add automatic
old-schema migration or retired CLI tool aliases. Standalone and workflow skills
now share canonical producer outputs; no consumer-side output normalization,
alias copying, or deduplication may be reintroduced. Regressions must exercise
direct canonical writing, pre-write rejection, and declared-input preservation.
Unsupported persisted formats must produce a clear validation error;
never rewrite user artifacts merely to make them appear current.
Active `merak-skills/*/SKILL.md` files are executable producer contracts. Any
skill that writes a versioned research artifact must declare its current schema
in frontmatter; the registry, prompt loader, and model invocation path all
validate that declaration before execution. A skill instruction that names a
different schema is a contract defect, not a model-choice issue.
`npm run check:standards` also rejects known retired adapter symbols and any
`aliases` entry reintroduced into the workflow artifact contract.

Module docstrings describe ownership and boundaries. Public state transitions,
hash/provenance operations, and persistence interfaces document their invariants
and failure behavior. Comments must match the current code, not a retired path.

`npm run verify:local` is the default V0/V1 handoff check. It performs frontend
type/lint checks, the non-regression size gate, and a small set of pure safety
tests. It does not start Electron, a backend listener, a workflow, a model call,
training, inference, remote execution, or simulation artifact generation.
