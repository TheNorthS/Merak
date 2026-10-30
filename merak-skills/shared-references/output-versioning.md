# Current Artifact Writing Protocol

All MERAK skill invocations use the same project-relative output layout. This
includes standalone invocations: no legacy-layout mode or path migration exists.

## Canonical ownership

- Literature: `literature/survey.md`, `literature/references.bib`.
- Idea report: `ideas/ideas.md`.
- Optional compact summary: `ideas/COMPACT_IDEA_CANDIDATES.md`; it is a distinct
  short summary and must not replace the full report.
- Novelty decision: `ideas/novelty_report.md`, `ideas/SELECTED_IDEA.json`.
- Refined proposal: `ideas/FINAL_PROPOSAL.md`.
- Experiment plan/tracker: `experiments/EXPERIMENT_PLAN.md`,
  `experiments/EXPERIMENT_TRACKER.md`.
- Refinement history: `experiments/refinement/`.
- Results analysis: `experiments/results/analysis.md`.
- Narrative: `NARRATIVE_REPORT.md`.
- Manuscript plan/source: `paper/PAPER_PLAN.md`, `paper/main.tex`,
  `paper/sections/`.
- Review: `review-stage/`; audit: `audit-results/`.
- Paper builds: `paper/`; presentation builds: `slides/`.
- Runtime-owned history, provenance and quality reports: `.merak/`.

The runtime producer contract and a bounded invocation identify the current
stage and exact targets. Do not generate every artifact in this list. Supporting
artifacts may be added inside the owning directory when they contain distinct
scientific content.

## Write directly

Write once to the canonical fixed path. Do not create a timestamped sibling,
root-level equivalent or alternate name for a gate artifact. There is no
consumer-side copying, moving or automatic deduplication. Fix a rejected path
in the producer's next Write/Edit call; do not bypass the rejection with Bash.

Use designated runtime tools for hashes, manifests, lifecycle state and
provenance. Do not author runtime metadata merely to make an artifact eligible.
Keep valid user inputs and accepted outputs; do not delete a failed artifact to
make a gate ignore it.

## History and recovery

Keep required per-round PDFs, proof/review receipts and content-addressed
snapshots in their declared revision/history locations. These are research
history, not alternate production-code implementations.

Read only canonical prerequisites or explicitly declared user inputs. A missing
canonical prerequisite is an owner-specific finding, not permission to probe,
copy or migrate historical equivalents.

State validity depends on the current schema, research-input identity and
semantic bindings. Age alone must not certify or invalidate a state. Unsupported
records remain unchanged and require a current producer operation; never reset
a research decision or opt into experiment execution during path repair.
