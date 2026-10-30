# MERAK local engineering rules

Read and follow `docs/ENGINEERING_STANDARDS.md` for every change.
Publication figures and tables must follow `docs/PUBLICATION_VISUAL_SYSTEM.md`.
Reference papers are quality exemplars, never universal layout templates.

- Do not grow a file listed in `docs/code-size-baseline.json`; extract first.
- Do not add production placeholders, demo paths, or fake-success behavior.
- Do not run a workflow, training, inference, remote job, GPU job, or scientific
  experiment without an explicit user command for that execution.
- Default verification is static analysis plus focused pure/local tests.
- Repair an artifact in its producer; consumers must not delete or bypass a
  failing upstream artifact.
- Runtime-owned hashes, statuses, timestamps, leases, and provenance are
  deterministic code responsibilities, not model-authored fields.
