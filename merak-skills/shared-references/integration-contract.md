# Integration Contract

When one MERAK skill delegates work to another (or to persistent project
state), the coupling must be **engineered**, not assumed. This document
formalizes what every cross-skill integration inside MERAK must provide.

Rule of thumb: **SKILL.md prose can *describe* an integration; it cannot
*guarantee* one.** Any integration whose silent failure would damage the
research result needs the components below. Prose-only "MUST invoke X"
has repeatedly failed in practice — the executor skips under context
pressure and the caller has no way to detect it.

## Known failure mode (why this contract exists)

Two bugs in the same week, same pathology:

1. **Assurance gate bypass (2026-04-21).** `/paper-writing` ran at
   `— effort: beast` silently skipped `/proof-checker`,
   `/paper-claim-audit`, and `/citation-audit` because each phase's
   content detector could return negative and the outer prose said
   "audit is optional."
2. **Research wiki ingest no-op (2026-04-21).** `/research-wiki init`
   created `research-wiki/papers/` but no paper ever landed there:
   `/arxiv`, `/alphaxiv`, `/deepxiv`, `/semantic-scholar`, `/exa-search`,
   raw `Read`/`WebFetch` — none carried a wiki-ingest hook, and the two
   that did (`/research-lit`, `/idea-creator`) only had soft prose
   ("optional and automatic").

Both bugs ship through the same gap: **one skill "called" another via
prose without a canonical helper, a concrete artifact, or a verifier**.

## Required components

Every integration between two MERAK skills (or between a skill and a
persistent project artifact) must provide all six:

### 1. Activation predicate — single, explicit, observable

A one-line test that says "does this integration fire in this context?"
Must be observable from outside the LLM (a file exists, an argument is
set, an environment variable is present). Not a vibe, not "probably
relevant."

- ✅ `if [ -d research-wiki/ ]`
- ✅ `if assurance == "submission"`
- ❌ "if the user seems to want this"

### 2. Canonical helper — one implementation, not copy-pasted

The business logic lives in **exactly one place** — a script under
`tools/` (canonical name, no path prefix), or a single subcommand of
an existing helper. Every caller invokes the same entrypoint, but
every caller must also resolve **where** that entrypoint lives,
because the helper may sit at any of:

- `<project>/.merak/tools/<helper>` — symlinked by `install_merak.sh` (Phase 0, #174)
- `<project>/tools/<helper>` — manual copy or running from inside the MERAK repo
- `$MERAK_REPO/tools/<helper>` — env var or auto-resolved from the install manifest

Every caller — including those primarily exercised from inside the
MERAK repo — MUST use the resolution chain. The chain's middle layer
(`tools/<helper>`) covers the in-repo case at the same code path,
with no special-casing needed. The exception that used to live here
("helpers run from inside MERAK repo may stay plain `tools/...`")
caused the canonical user-report bug: `/paper-writing` invoked from
a downstream paper project could not find `verify_paper_audits.sh`
because the prose endorsed the hardcoded form.

#### Resolver block (lookup only — failure policy is separate)

```bash
# Canonical strict-safe variant: works whether or not the caller has
# `set -e` enabled. The manifest read only runs when the file exists,
# and `|| true` consumes a non-zero awk exit so chain evaluation
# continues. Run `chmod +x` not required: the block uses `[ -f ]`.
cd "$(git rev-parse --show-toplevel 2>/dev/null || pwd)" || exit 1
if [ -z "${MERAK_REPO:-}" ] && [ -f .merak/installed-skills.txt ]; then
    MERAK_REPO=$(awk -F'\t' '$1=="repo_root"{print $2; exit}' .merak/installed-skills.txt 2>/dev/null) || true
fi
HELPER=".merak/tools/<helper>"
[ -f "$HELPER" ] || HELPER="tools/<helper>"
[ -f "$HELPER" ] || { [ -n "${MERAK_REPO:-}" ] && HELPER="$MERAK_REPO/tools/<helper>"; }
[ -f "$HELPER" ] || HELPER=""
```

After the resolver runs, `$HELPER` is either the resolved absolute or
relative path, or the empty string. Use a semantic variable name in
real callers (`AUDIT_VERIFIER`, `TRACE_HELPER`, `WIKI_SCRIPT`,
`IMAGE2_HELPER`, …) so a single SKILL that resolves multiple helpers
does not clobber one with another.

If the SKILL is invoked from a subdirectory of a non-git project (no
`.git/` anywhere up the tree), `git rev-parse --show-toplevel` fails
and the `|| pwd` fallback keeps the resolver in the current directory.
SKILLs that need to discover `.merak/` from a deeper subdirectory MUST
either run from project root or set `$MERAK_REPO` explicitly — the
resolver intentionally does not walk parent directories.

#### Failure policy (chosen per integration)

The resolver does **not** decide what happens when the helper is
missing. Each calling SKILL must pick exactly one policy below based
on how the helper contributes to the research outcome:

**A. Load-bearing gate — unresolved helper must block.** Use for
verifiers whose exit code gates submission readiness (e.g.
`verify_paper_audits.sh` under `assurance: submission`).

```bash
[ -n "$AUDIT_VERIFIER" ] || {
  echo "ERROR: verify_paper_audits.sh not resolved at .merak/tools/, tools/, or \$MERAK_REPO/tools/." >&2
  echo "       assurance=submission requires the verifier; aborting Final Report." >&2
  exit 1
}
```

**B. Optional side-effect — unresolved helper warns and skips.** Use
when the SKILL's primary output is still delivered without the
helper (e.g. `research_wiki.py ingest_paper` — idea ranking still
gets produced, only the wiki side-effect is missed).

```bash
[ -n "$WIKI_SCRIPT" ] || {
  echo "WARN: research_wiki.py not resolved; primary output unaffected, wiki side-effect skipped." >&2
  echo "      Fix: rerun bash tools/install_merak.sh, export MERAK_REPO, or copy the helper to tools/." >&2
}
[ -n "$WIKI_SCRIPT" ] && python3 "$WIKI_SCRIPT" ingest_paper research-wiki/ --arxiv-id "$id"
```

**C. Forensic helper — unresolved means write artifacts directly.**
Use when the helper produces a record the SKILL is contractually
required to leave behind (e.g. `save_trace.sh`). The fallback is
**not** "skip"; it is "write the schema artifacts inline."

```bash
[ -n "$TRACE_HELPER" ] || {
  echo "WARN: save_trace.sh not resolved; writing trace files directly per review-tracing.md schema." >&2
}
if [ -n "$TRACE_HELPER" ]; then
  bash "$TRACE_HELPER" --skill "$SKILL" --purpose "$PURPOSE" --model "$MODEL" \
       --thread-id "$THREAD" --prompt "$PROMPT" --response "$RESPONSE"
else
  # Required fallback: write run.meta.json, request.json, response.md, meta.json
  # directly per review-tracing.md schema. Do NOT silently skip unless
  # `--- trace: off` was explicitly requested.
  ...
fi
```

**D1. Primary helper with first-success cascade — try N sources in
priority order, accept first success.** Use when the SKILL needs
one paper-discovery source and falls back across alternatives.

The example below is POSIX-sh safe (`${VAR:-}` defaults plus
explicit `source_used=""` init) so the same snippet works under
`#!/bin/sh`, `#!/bin/bash`, `set -e`, and `set -u`.

```bash
source_used=""
if [ -n "${S2_FETCHER:-}" ]; then
  if python3 "$S2_FETCHER" --query "$Q" > results.jsonl; then
    source_used="semantic_scholar"
  else
    echo "WARN: semantic_scholar_fetch.py invocation failed; trying arxiv." >&2
    S2_FETCHER=""  # force cascade
  fi
fi
if [ -z "$source_used" ] && [ -n "${ARXIV_FETCHER:-}" ]; then
  echo "WARN: semantic_scholar_fetch.py not resolved or failed; falling back to arxiv_fetch.py." >&2
  if python3 "$ARXIV_FETCHER" --query "$Q" > results.jsonl; then
    source_used="arxiv_fallback"
  fi
fi
if [ -z "$source_used" ]; then
  echo "ERROR: no fetcher resolved or succeeded; cannot retrieve papers." >&2
  exit 1
fi
```

The `if helper-invocation; then ... else ...` wrapper consumes the
helper's exit code so the cascade fires even under `set -e`.

**D2. Multi-source aggregate — invoke every resolved source,
aggregate results.** Use when the SKILL ranks or dedupes across all
available sources (e.g. `/research-lit` querying S2 + arxiv +
OpenAlex + Exa). Each source's success/failure is recorded; the
SKILL proceeds with a (possibly partial) aggregate if at least one
source contributed.

The example below is POSIX-sh safe (delimited-string accumulator
instead of bash arrays, so the snippet works under `dash`,
macOS bash 3.2, etc.):

```bash
sources_used=""
sources_count=0
append_source() {
  sources_used="${sources_used:+$sources_used,}$1"
  sources_count=$((sources_count + 1))
}

if [ -n "${S2_FETCHER:-}" ]; then
  if python3 "$S2_FETCHER" --query "$Q" >> results.jsonl 2>>fetch.log; then
    append_source "semantic_scholar"
  else
    echo "WARN: semantic_scholar_fetch.py failed; see fetch.log" >&2
  fi
fi
if [ -n "${ARXIV_FETCHER:-}" ]; then
  if python3 "$ARXIV_FETCHER" --query "$Q" >> results.jsonl 2>>fetch.log; then
    append_source "arxiv"
  else
    echo "WARN: arxiv_fetch.py failed; see fetch.log" >&2
  fi
fi
# ... repeat for openalex, exa, deepxiv ...
if [ "$sources_count" -eq 0 ]; then
  echo "ERROR: no fetcher resolved or succeeded; aggregate empty." >&2
  exit 1
fi
echo "Aggregated from: $sources_used" >&2
```

Record `sources_used` (or equivalent) in the SKILL's output manifest
so downstream consumers know which sources contributed.

**E. Diagnostic / report helper — non-zero exit is captured, not propagated.**
Use when the helper's role is to surface drift to humans rather than
gate workflow correctness (e.g. `verify_wiki_coverage.sh` exits 1
when wiki coverage has gaps, but coverage is not load-bearing on any
research outcome). The SKILL records the diagnostic outcome to a
report file but does not propagate the exit code as a workflow gate.

```bash
if [ -n "$WIKI_COVERAGE_DIAG" ]; then
  # Wrap the helper call in if/then/else so `set -e` does not exit
  # the SKILL when the helper exits non-zero to report gaps.
  if bash "$WIKI_COVERAGE_DIAG" research-wiki/ > coverage_report.txt; then
    diag_exit=0
  else
    diag_exit=$?
  fi
  echo "Coverage diagnostic written to coverage_report.txt (exit=$diag_exit)" >&2
  # Do NOT propagate $diag_exit; this is a report, not a gate.
else
  echo "WARN: verify_wiki_coverage.sh not resolved; coverage diagnostic skipped (non-load-bearing)." >&2
fi
```

`wiki-helper-resolution.md` is the research-wiki-specific instance
of this generic resolver, and is the precedent for everything in §2.

#### Self-contained owner skill

Single-owner helpers live in the owning SKILL's `scripts/` subdirectory.
When an owner skill invokes its own helper, it resolves that location only
from the absolute `MERAK_SKILLS_PATH` published by the MERAK server:

```bash
HELPER="${MERAK_SKILLS_PATH:?MERAK_SKILLS_PATH is required}/<skill-name>/scripts/<helper>"
[ -f "$HELPER" ] || { echo "ERROR: missing registered helper $HELPER" >&2; exit 1; }
```

Three properties of layer 0:

1. **Single-skill only.** Only the owning SKILL uses layer 0. Cross-skill
   helpers (`research_wiki.py` consumed by 9 SKILLs; `save_trace.sh`
   by 14) stay on the shared-runtime chain because they have multiple owners.

2. **MERAK-native feature.** `${MERAK_SKILLS_PATH}` is published by the
   MERAK server. Missing registration is a configuration error; no local
   coding-agent CLI or alternate repository path is consulted.

The per-helper policy table at the end of §2 marks Phase 3 moves
with a "Phase 3.N move" note pointing at the new canonical location.

#### Per-helper policy assignments

Every helper invoked from any SKILL.md (single-skill or shared
across skills) is classified below so that downstream SKILLs in
Phase 1.2-1.7 do not have to guess. Pure developer utilities that
are never invoked from a SKILL.md — the MERAK installer/update scripts,
manual setup helpers, format converters, the `meta_opt/` hook scripts,
and `watchdog.py` — are out of scope.
If a future helper does not fit any policy, extend the taxonomy
here first.

| Helper (canonical name) | Policy | Rationale |
|---|---|---|
| `verify_paper_audits.sh` | A (gate) | Exit code is the source of truth for submission readiness |
| `save_trace.sh` | C (forensic) | Trace artifacts are load-bearing for audit traceability and reviewer-independence audit |
| `research_wiki.py ingest_paper` (caller skills) | B (side-effect) | Primary output (idea ranking, paper summary) is delivered without wiki ingestion |
| `research_wiki.py` (in `/research-wiki` itself) | A (gate) | The SKILL is the wiki tool; missing helper means no functionality (Variant A in `wiki-helper-resolution.md`) |
| `verify_wiki_coverage.sh` | E (diagnostic) | Reports coverage gaps; not load-bearing on any research outcome |
| `verify_papers.py` | D1 (primary + fallback cascade) | Filters candidate papers via arXiv/CrossRef/S2 cross-checks; when unresolved **or** invocation fails, callers emit a degraded `verified_papers.json` tagging every candidate `status=unverified, method=none` with explicit WARN |
| `arxiv_fetch.py`, `semantic_scholar_fetch.py`, `deepxiv_fetch.py`, `exa_search.py`, `openalex_fetch.py` | D2 (multi-source aggregate) when SKILL queries multiple sources (e.g. `/research-lit`); D1 (cascade) when a single source suffices | Each fetcher is one paper-discovery source; SKILLs aggregate or cascade across resolved sources and record which contributed |
| `extract_paper_style.py` | A when activation predicate `literal "— style-ref:" or equivalent in $ARGUMENTS` is true; not invoked otherwise | If the user asked for style transfer and the helper is unresolved, the SKILL cannot satisfy the request |
| `figure_renderer.py` | A (skill-local gate, single-skill) | `figure-spec` cannot produce vector SVG output without the registered skill-local renderer. |
| `experiment_queue/queue_manager.py`, `experiment_queue/build_manifest.py` | A (skill-local gate, single-skill) | `/experiment-queue` requires its registered skill-local scheduler helpers. |
| `overleaf_audit.sh` | E (diagnostic) | Reports overleaf sync drift; surfaces gaps but does not gate the parent workflow |
| `evidence_check.py` (in `/result-to-claim`, `/paper-claim-audit`) | B (side-effect) | Deterministic pre-check that downgrades hallucinated-evidence claims before the Codex jury; if unresolved the jury still runs (warn-and-skip). A deterministic gate DRIVES, it does not ACQUIT — `verified` means the cited number exists, not that it supports the claim |
| `capture_filter.py` (in `/research-wiki` capture, `/meta-optimize` Step 3) | B (side-effect) | Anti-self-poisoning screen on durable captures; if unresolved the capture proceeds (the screen is advisory, and a passing screen is never an ACCEPT — the cross-model jury still judges) |
| `provenance.py` (in `/meta-apply`; `assert_cross_family`/`stamp`) | A (gate) | The landing acquittal: if unresolved, `/meta-apply` cannot verify author≠reviewer family and MUST refuse to land (fail-closed). `stamp()` itself raises on same-family, so an unresolved or same-family case blocks the corpus mutation |
| `run_state.py` (in `/research-pipeline`) | B (side-effect) | Resumability is a convenience; the pipeline still runs end-to-end without it (warn-and-skip, never block). Predicate = `RESUMABLE` / `— resume <run_id>` set |

When a SKILL invokes a helper not listed above, add the row here as
part of the same commit and link the chosen policy. Inconsistency in
this table is the cheapest place to catch policy drift.

#### Examples

- ✅ Resolved-via-chain invocation: `python3 "$WIKI_SCRIPT" ingest_paper <root> --arxiv-id <id>` (where `$WIKI_SCRIPT` was set by the chain above with `<helper>=research_wiki.py`)
- ✅ Resolver block + policy A above for `verify_paper_audits.sh` (submission-gate verifier)
- ❌ Hard-coded `python3 tools/research_wiki.py …` from a downstream skill that may run in a project without `tools/` on disk — it silently exits 2 and the caller proceeds with no side effect, which is exactly the failure mode that left a real user's `research-wiki/` empty for a week.
- ❌ N skills each paraphrasing the same 10-line bash snippet. When one drifts, they all drift.

If the same 3+ lines of prose appear in more than two SKILL.md files,
factor them into a helper.

### 3. Concrete artifact or log entry

Successful execution must leave an observable side effect: a file, a
JSON record, a log line. The artifact is the receipt — something a
third party (verifier, code reviewer, human auditor) can inspect to
answer "did this integration run?"

- ✅ `paper/PROOF_AUDIT.json` with the 6-state verdict schema
- ✅ `research-wiki/papers/<slug>.md` + `research-wiki/log.md` append
- ❌ "the model said it ran"

### 4. Visible checklist — for long workflows

If the integration fires inside a multi-step workflow (paper-writing
Phase 6, idea-discovery Phase 7, etc.), render a **visible checkbox
block** at the start of the phase so the executor has to confront each
row before claiming done. Prose-only "MUST" inside a long SKILL.md is
the first thing to get skipped.

```
📋 Submission audits required before Final Report:
   [ ] 1. /proof-checker   → paper/PROOF_AUDIT.json
   [ ] 2. /paper-claim-audit → paper/PAPER_CLAIM_AUDIT.json
   [ ] 3. /citation-audit  → paper/CITATION_AUDIT.json
   [ ] 4. Resolve $AUDIT_VERIFIER via §2 (canonical name verify_paper_audits.sh)
          then: bash "$AUDIT_VERIFIER" paper/ --assurance submission
   [ ] 5. Block Final Report iff verifier exit code != 0
```

Cheap, and empirically resists lazy skipping. Skip only for single-step
invocations (one-off skills like `/arxiv 2501.12345`).

### 5. Backfill / repair command — explicit manual fallback

An escape hatch for when the integration didn't fire. Users must be
able to run a command that **declares** the missed inputs and ingests
them retroactively. Prefer explicit arguments over trace-scanning — the
helper should not have to guess what to backfill.

- ✅ `/research-wiki sync --arxiv-ids 2501.12345,1706.03762`
- ✅ `/research-wiki sync --from-file ids.txt`
- ⚠️ `/research-wiki sync` that scans `.merak/traces/` for arxiv IDs —
     only as a best-effort secondary mode, not the primary UX, and
     clearly labeled as heuristic.

### 6. Verifier or diagnostic (only when load-bearing)

If silent failure of this integration would damage the research result
(wrong numbers shipped to a conference, claims unsupported by
evidence, citations in wrong context), a verifier script must exist
whose exit code is the source of truth for downstream gates.

- ✅ `verify_paper_audits.sh` — exit 1 blocks Final Report (resolved per §2)
- ✅ `verify_wiki_coverage.sh` — diagnostic only, reports gaps but
     does not block (coverage is not load-bearing on any research
     outcome; resolved per §2)

Verifiers must be **external processes** (not LLM self-report), must
validate **concrete artifacts** (§3) against a schema, and must emit a
structured report callers can parse.

A diagnostic-only verifier (no exit-1 blocking) is still valuable — it
surfaces drift to humans. But do not market a diagnostic as a gate.

## Anti-patterns to refuse in review

When reviewing a new integration proposal, reject any of:

- **"Optional and automatic"** — contradicts itself; if it's automatic,
  it's not optional. Pick one and mean it.
- **"The skill will intelligently decide"** — indecision surface, not
  a predicate (§1).
- **"Copy the following 10 lines into each caller"** — missing helper
  (§2); will drift within a month.
- **"The reviewer can see from the logs that..."** — if the evidence is
  unstructured logs, write a schema and make it an artifact (§3).
- **"Users should remember to..."** — missing backfill (§5); humans
  don't reliably remember.
- **"Trust the LLM to self-report completion"** — missing verifier (§6)
  when the failure is load-bearing.

## Known MERAK integrations under this contract

Helper names in the table below are **canonical names**; callers
resolve actual paths via §2.

| Integration | Predicate | Helper | Artifact | Checklist | Backfill | Verifier |
|---|---|---|---|---|---|---|
| Submission audits (`max`/`beast`) | `paper/.merak/assurance.txt = submission` | `verify_paper_audits.sh` + 3 audit skills emit JSON | `paper/PROOF_AUDIT.json`, `PAPER_CLAIM_AUDIT.json`, `CITATION_AUDIT.json` + `paper/.merak/audit-verifier-report.json` | Phase 6.0 pre-flight checklist | Rerun the failed audit | `verify_paper_audits.sh` (exit 1 blocks) |
| Research wiki ingest | `research-wiki/` exists | `research_wiki.py ingest_paper` | `research-wiki/papers/<slug>.md` + `log.md` entry | Step in each paper-reading skill | `research_wiki.py sync --arxiv-ids …` | `verify_wiki_coverage.sh` (diagnostic) |

When adding a new cross-skill integration, add a row to the table above
and confirm all six columns are populated.

## See Also

- `shared-references/assurance-contract.md` — implementation of the
  paper-writing submission gate under this contract
- `shared-references/reviewer-independence.md` — the adjacent contract
  for cross-model review (executor never filters reviewer inputs)
- `tools/verify_paper_audits.sh`, `tools/research_wiki.py ingest_paper`,
  `tools/verify_wiki_coverage.sh` — current canonical helpers
