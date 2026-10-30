# Repository maintenance

## Source of truth

Keep one implementation for each domain responsibility. Schema numbers identify
the current stored contract; they are not a requirement to ship old converters.
Changing a renderer version is independent of changing scientific evidence.
Current-schema rendering may be refreshed before owner revalidation. Unsupported
scientific schemas are rejected without modifying the original project files.

Manuscript plans live in `paper/PAPER_PLAN.md`; budgets in
`paper/PAPER_BUDGET.json`. Source hashes belong to runtime-owned build records.
Table producers initialize hashes after writing data and LaTeX. Acceptance gates
only validate those bindings: they must not fill missing hashes or upgrade an
unregistered manifest while accepting it.

Standalone skills and workflow sessions share the producer contract in
`server/services/artifact_contract.py`. Fixed outputs are explicitly declared in
skill frontmatter; dynamic assets use bounded invocation targets. Write/Edit
reject incompatible paths before mutation. Gate preparation and owner revision
never move, copy, or delete an equivalent file to satisfy a missing output.

Figure specifications are current only at schema 4 with
`publication_label_schema: 1`. Each Phase-2b asset declares typed public labels
and `producer_kind`. Deterministic source files are generated only from their
typed inputs; model-authored sources are never replaced by a deterministic
fallback. Candidate transactions live briefly under `.merak/transactions/` and
must be removed on both commit and rollback.

## Comments and interfaces

Document module ownership, input/output contracts, failure handling, and state
invariants. In particular, explain semantic versus byte hashes, input freeze,
artifact ownership, lock/lease boundaries, and authorization requirements.
Avoid syntax narration and stale claims about old implementations.

## Retention policy

| Category | Retention |
| --- | --- |
| Active source, reusable development tools, focused regression tests | Keep |
| Refactor-only extraction/proposal/generation scripts | Remove after checking references |
| `.pytest-tmp-*`, Python bytecode, pytest/type/lint caches | Disposable; regenerate locally |
| `output/`, research figures/PDFs, user project artifacts | Preserve; never treat as refactor debris |
| `.env`, user settings, SQLite databases, credentials | Preserve locally; do not commit or print contents |
| `node_modules/`, `dist/`, `dist-electron/` | Generated, but do not remove a user's installed/running application as incidental cleanup |

## Release layout

- Keep only the current Merak installer, source ZIP, checksums, and verification
  receipts in `release/`; retired product-name packages can be removed after a
  replacement is verified.
- `resources/icon.svg` and `resources/icon-light.svg` are generated from the
  shared geometry in `scripts/generate-icon.py`. Both are used by the UI.
- `docs/images/*-dark.png` and `docs/images/*-light.png` are published software
  screenshots. Replace obsolete screenshots when updating the README.
- `.backend-build/`, temporary pytest directories, obsolete build virtual
  environments, and isolated screenshot profiles are disposable after their
  owning build or check finishes. Keep the active build environment.
- Keep real research outputs and run history in place. Moving them merely to
  tidy the repository can break persisted project paths and provenance.

Before deleting directories, validate absolute targets inside the intended
workspace and exclude reparse-point roots. Delete with literal paths in one
shell. Do not derive destructive targets from Git's untracked-file list.

## Verification

Use V0 static checks and focused V1 tests with temporary fixtures. Do not start a
workflow, a provider call, or scientific execution for repository maintenance.
Record the actual checks; passing local checks is not proof of end-to-end
scientific or visual quality. Cleanup and current-only contracts intentionally
do not guarantee that unpublished historical run records can resume.
