# Report-scoped revision in the original workflow

The original 13 stages, UI layout, model API backend, scientific producers and
final review/audit/compile gates remain in use. No external agent CLI is added.

## Implemented path

Review/audit gate failures with exact existing bibliography, semantic result-analysis,
narrative or authored section targets enter one persisted `report_revisions` worklist before the legacy
single-owner loop. Every owner edits its exact permitted source paths first.
Only Read/Edit/Glob/Grep and the selected bibliography retrieval tools are
available; shell, experiments, nested review and runtime-state writes are absent.

The worklist stores original evidence, file hashes, findings, completed owners,
refresh steps and the current round. Edits do not resolve findings. Existing
acceptance is retained in `last_accepted_execution`, while current publication
validation is marked pending. The existing node UI displays revision/recheck
labels, including after project reopening.

An isolated API reviewer assesses scientific meaning against before/after
content. Local/linked changes may proceed only with no unresolved original
finding. Research changes and uncertain scope stop for reassessment rather
than silently taking the local route. Other producer types (experiment,
runtime-owned result analysis, figure generators and tables) retain their existing explicit
producer repair path; they are not relabeled as bibliography/text edits.

Unchanged specialist documents whose inputs changed receive a read-only
independent source review. Original producer trace and output hashes remain;
the new dependency receipt binds current input bytes and the native model
response. An invalid or changed output requires producer repair. The source
review cannot manufacture an experiment or count as scientific validation.

Current plan preparation and the existing staged paper/compilation producers
refresh publication outputs after all authored edits. Existing research nodes
receive fresh read-only gates where applicable; no local path invokes an
experiment or results producer. Final independent review and audit still run;
only their accepted state transition closes the report findings.

## Recovery and boundedness

An active repair resumes before ordinary dependency invalidation. Only its
consumer is scheduled while the transaction is unfinished. No accepted status
is synthesized. Completed owners and successful refresh steps are reused;
unexpected target/source changes stop rather than overwrite user edits.
If interrupted after a file write but before its durable completion record,
the outcome is treated as ambiguous and requires reassessment, not blind replay.

Report rounds share the existing configured revision limit per consumer;
renaming a finding cannot create unlimited rounds. Provider retries do not
increment report rounds. State write failures propagate. Completed/cancelled
runs cannot start repair without explicit resume. Existing research-level
budget/invalidation remains for actual research changes.

## Verification

Tests cover multi-owner ordering, no experimental/whole-node execution on local
repairs, no early resolution, historical acceptance, changed science, disk
failure, external edits, interrupted repair routing, refresh-step reuse,
dependency receipt tampering and stale-source refusal.

Commands: `python -m pytest` in the project's development environment against
`test_report_revision_workflow.py`, `test_report_revision_refresh.py` and related
resume/specialist/write-scope/end-to-end regressions; `npm run typecheck`,
`npm run lint`, `npm run verify:local`, strict code standards. Pure tests mock
model responses and do not constitute real scientific workflow acceptance.

Release status and remaining verification limits are documented in
[RELEASE_0.1.1.md](RELEASE_0.1.1.md). Raw model traces remain outside the source repository.
