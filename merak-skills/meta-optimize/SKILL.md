---
name: meta-optimize
description: "Analyze MERAK usage logs and propose optimizations to SKILL.md files, reviewer prompts, and workflow defaults. Outer-loop harness optimization inspired by Meta-Harness (Lee et al., 2026). Use when user says \"优化技能\", \"meta optimize\", \"improve skills\", \"分析使用记录\", or wants to optimize MERAK's own harness components based on accumulated experience."
argument-hint: [target-skill-or-all]
allowed-tools: Bash(*), Read, Grep, Glob, reviewer_api, reviewer_api_reply
---

# Meta-Optimize: Outer-Loop Harness Optimization for MERAK

Analyze accumulated usage logs and propose optimizations for: **$ARGUMENTS**

## Privilege boundary — this skill is a READ-ONLY PRODUCER

meta-optimize **proposes**; it does not **land**. The mutation of the skill corpus
is the exclusive job of a separate, human-invoked skill: [`/meta-apply`](../meta-apply/SKILL.md).
This split is structural, not advisory — it is why a missed instruction cannot let
this loop apply its own patch (the self-acquittal failure mode):

- **No `Write`/`Edit` tool.** This skill cannot edit a SKILL.md / shared-reference /
  any corpus file with the frictionless mutators. Its only outputs are the REPORT and
  staged patch files, written under `.merak/meta/` (a scratch area, never the corpus).
- **No apply step.** There is no in-skill "apply the patch" path (see Step 6). The
  producer ends by *staging* approved patches for `/meta-apply`; a human must then
  invoke `/meta-apply` to land them. That human action is the landing gate.
- **MERAK enforces the write boundary.** Run this skill under the MERAK
  `workflow_artifacts` policy with its writable output scope restricted to
  `.merak/meta/`. The runtime must reject corpus targets before dispatching a tool call;
  this protection belongs to MERAK's tool policy and filesystem sandbox, not to an
  external coding-agent hook. Keep `Bash` only for read-only analysis and staging files
  under `.merak/meta/`. A corpus mutation without a separate `/meta-apply` provenance
  record is invalid even if it was produced through an indirect shell command.

See [`shared-references/acceptance-gate.md`](../shared-references/acceptance-gate.md):
a loop can DRIVE (propose, review) same-model, but the ACQUITTAL that lands a change
must be cross-model (Step 4 jury) **and** the landing must be a separate human-gated
act (`/meta-apply`).

## Context

MERAK is a **research harness** — a system of skills, bridges, workflows, and artifact contracts that wraps around LLMs to orchestrate research. This skill implements a prototype **outer loop** that observes how the harness is used and proposes improvements to the harness itself (not to the research artifacts it produces).

Inspired by Meta-Harness (Lee et al., 2026): the key insight is that harness design matters as much as model weights, and harness engineering can be partially automated by logging execution traces and using them to guide improvements.

## What This Skill Optimizes (Harness Components)

| Component | Example | Optimizable? |
|-----------|---------|:---:|
| SKILL.md prompts | Reviewer instructions, quality gates, step descriptions | Yes |
| Default parameters | `difficulty: medium`, `MAX_ROUNDS: 4`, `threshold: 6/10` | Yes |
| Convergence rules | When to stop the review loop, retry counts | Yes |
| Workflow ordering | Skill chain sequence within a workflow | Yes |
| Artifact schemas | What fields go in EXPERIMENT_LOG.md, ideas/ideas.md | Cautious |
| MCP bridge config | Which reviewer model, routing rules | No (infra) |

**Not optimized**: The research artifacts themselves (papers, code, experiments). That's what the regular workflows do.

## Prerequisites

1. **MERAK event logging must be active.** The backend/workflow runtime records
   tool and lifecycle events in `.merak/meta/events.jsonl`; no coding-agent hook or
   user-level settings file is required.
2. **Sufficient data.** At least 5 complete workflow runs logged in `.merak/meta/events.jsonl`. The skill will check and warn if insufficient.

## Workflow

### Step 0: Check Data Availability

```bash
EVENTS_FILE=".merak/meta/events.jsonl"
if [ ! -f "$EVENTS_FILE" ]; then
    echo "ERROR: No event log found at $EVENTS_FILE"
    echo "Enable MERAK project event logging and run a workflow before meta-optimize"
    exit 1
fi

EVENT_COUNT=$(wc -l < "$EVENTS_FILE")
SKILL_INVOCATIONS=$(grep -c '"skill_invoke"' "$EVENTS_FILE" || echo 0)
SESSIONS=$(grep -c '"session_start"' "$EVENTS_FILE" || echo 0)

echo "📊 Event log: $EVENT_COUNT events, $SKILL_INVOCATIONS skill invocations, $SESSIONS sessions"

if [ "$SKILL_INVOCATIONS" -lt 5 ]; then
    echo "⚠️  Insufficient data (<5 skill invocations). Continue using MERAK normally and re-run later."
    exit 0
fi
```

### Step 1: Analyze Usage Patterns

Read `.merak/meta/events.jsonl` and compute:

**Frequency analysis:**
- Which skills are invoked most often?
- Which slash commands do users type most?
- What parameter overrides are most common? (These suggest bad defaults.)

**Failure analysis:**
- Which tools fail most often? In which skills?
- What error patterns repeat? (OOM, import, compilation, timeout)
- How many auto-debug retries per workflow run?

**Convergence analysis (for auto-review-loop):**
- Average rounds to reach threshold
- Score trajectory shape (fast improvement? plateau? oscillation?)
- Which review round catches the most critical issues?
- Do users override difficulty mid-run?

**Human intervention analysis:**
- Where do users interrupt with manual prompts during workflows?
- What manual corrections do users make most? (These indicate skill gaps.)

Present findings as a structured summary table.

### Step 2: Identify Optimization Targets

Based on Step 1, rank optimization opportunities by expected impact:

```markdown
## Optimization Opportunities (ranked)

| # | Target | Signal | Proposed Change | Expected Impact |
|---|--------|--------|-----------------|-----------------|
| 1 | auto-review-loop default threshold | Users override to 7/10 in 60% of runs | Change default from 6/10 to 7/10 | Fewer manual overrides |
| 2 | experiment-bridge retry count | 40% of runs hit max retries on OOM | Add OOM-specific recovery (reduce batch size) | Fewer failed experiments |
| 3 | paper-write de-AI patterns | Users manually fix "delve" in 80% of runs | Add "delve" to default watchword list | Fewer manual edits |
```

If `$ARGUMENTS` specifies a target skill, focus analysis on that skill only.
If `$ARGUMENTS` is empty or "all", analyze all skills with sufficient data.

### Step 3: Generate Patch Proposals

For each optimization target, generate a concrete diff:

```diff
--- a/skills/auto-review-loop/SKILL.md
+++ b/skills/auto-review-loop/SKILL.md
@@ -15,7 +15,7 @@
 ## Constants
 
-- **SCORE_THRESHOLD = 6** — Minimum review score to accept.
+- **SCORE_THRESHOLD = 7** — Minimum review score to accept. (Raised based on usage data: 60% of users overrode to 7+.)
```

**Rules for patch generation:**
- One patch per optimization target
- Each patch must include a comment explaining WHY (with data from the log)
- Patches must be minimal — change only what the data supports
- Never change artifact schemas or MCP bridge config in v1
- Never change behavior that would break existing user workflows
- **Anti-self-poisoning screen** (see [`shared-references/capture-antipatterns.md`](../shared-references/capture-antipatterns.md)):
  run a proposed patch's rationale through `tools/capture_filter.py` (resolve via
  the canonical chain). NEVER propose a change that encodes a **negative
  tool-capability claim** ("provider X cannot…", "provider Y is broken") or a **one-off /
  transient failure** as a durable rule — those harden into self-cited refusals.
  Encode the *fix / the flag needed / the workaround*, not "X can't do Y".

### Step 4: Cross-Model Review of Patches (ADVISORY pre-screen)

> This review is **advisory** — it sharpens the Step-5 REPORT so the human can decide
> what to stage. It is **not** the landing verdict. The binding cross-model jury runs
> later, at landing, inside [`/meta-apply`](../meta-apply/SKILL.md), on the actual staged
> diff (a producer-relayed verdict would be forgeable). Record this result as
> `advisory_screen` only.

Send each patch to the configured independent Reviewer provider at the
strongest available review effort:

```
reviewer_api:
  config: {"model_reasoning_effort": "xhigh"}
  prompt: |
    You are reviewing a proposed optimization to an MERAK SKILL.md file.
    
    ## Original Skill (relevant section)
    [paste original]
    
    ## Proposed Patch
    [paste diff]
    
    ## Evidence from Usage Log
    [paste summary stats]
    
    Review this patch:
    1. Does the evidence support the change?
    2. Could this change hurt other use cases?
    3. Is the change minimal and safe?
    4. Score 1-10: should this be applied?
    
    If score < 7, explain what additional evidence would be needed.
```

### Step 5: Present Results

Output a structured report:

```markdown
# MERAK Meta-Optimization Report

**Date**: [today]
**Data**: [N] events, [M] skill invocations, [K] sessions
**Target**: [skill name or "all"]

## Proposed Changes

### Change 1: [title]
- **Target**: [skill/file:line]
- **Signal**: [what the data shows]
- **Patch**: [diff]
- **Reviewer Score**: [X/10]
- **Reviewer Notes**: [summary]
- **Status**: ✅ Recommended / ⚠️ Needs more data / ❌ Rejected

### Change 2: ...

## Changes NOT Made (insufficient evidence)
- [pattern observed but too few samples]

## Recommendations
- [ ] Apply Change 1 (reviewer approved)
- [ ] Collect more data for Change 3 (need N more runs)
- [ ] Consider manual review of Change 2

## Next Steps
This skill only **proposes**. To land changes: tell me which to stage, then run
`/meta-apply` (a separate, human-invoked applier that re-checks the cross-model
verdict before mutating anything). meta-optimize never applies.
```

### Step 6: Stage approved patches for `/meta-apply` (NO in-skill apply)

This skill does **not** apply anything. After the user has read the Step-5 REPORT and
indicated which changes to land, **stage** them for the privileged applier:

1. For each approved change `N`, write its unified diff to
   `.merak/meta/pending/<NN>_<skill>.diff` and append a row to
   `.merak/meta/pending/manifest.jsonl`:
   `{patch: "<NN>_<skill>.diff", target: "<corpus path>", author_model: "<executor>",
   advisory_screen: "pass|kill", advisory_reason: "<one line>"}`.
   The `advisory_screen` (your Step-4 independent-reviewer pre-screen) is **advisory only** — it helps
   the human read the REPORT. It is **NOT** the landing verdict and `/meta-apply` does not
   trust it: a producer-written verdict would be forgeable. The binding cross-model jury
   runs **at landing, inside `/meta-apply`,** on the actual staged diff.
2. Tell the user: *"Staged M patches. Run `/meta-apply` to judge & land them."*

The backup → **fresh jury-at-landing** → apply → **provenance stamp** → log all happen
inside [`/meta-apply`](../meta-apply/SKILL.md). meta-optimize never touches the corpus and
never produces the acquittal.

**Never apply in this skill. Landing is `/meta-apply` + a fresh jury + a human, always.**

## Key Rules

- **Log-driven, not speculative.** Every proposed change must cite specific data from the event log. No "I think this would be better."
- **Minimal patches.** Change one thing at a time. Don't rewrite entire skills.
- **Reviewer-gated.** Every patch goes through cross-model review before recommendation.
- **Reversible.** Always back up before applying. Always log what changed.
- **User-approved.** Never auto-apply. Present, explain, let the user decide.
- **Honest about uncertainty.** If the data is insufficient, say so. Don't optimize on noise.
- **Portable.** Optimizations should improve the skill for all users, not just one user's style. If a change seems user-specific, flag it.

## Event Schema Reference

The log at `.merak/meta/events.jsonl` contains JSONL records with these shapes:

```jsonl
{"ts":"...","session":"...","event":"skill_invoke","skill":"auto-review-loop","args":"difficulty: hard"}
{"ts":"...","session":"...","event":"PostToolUse","tool":"Bash","input_summary":"pdflatex main.tex"}
{"ts":"...","session":"...","event":"reviewer_call","tool":"reviewer_api","input_summary":"review..."}
{"ts":"...","session":"...","event":"tool_failure","tool":"Bash","input_summary":"python train.py"}
{"ts":"...","session":"...","event":"slash_command","command":"/auto-review-loop","args":""}
{"ts":"...","session":"...","event":"user_prompt","prompt_preview":"change difficulty to hard"}
{"ts":"...","session":"...","event":"session_start","source":"merak","provider":"reviewer-provider","model":"configured-model"}
{"ts":"...","session":"...","event":"session_end"}
```

## Triggering

This skill is NOT part of the standard W1→W1.5→W2→W3→W4 pipeline. It is a **maintenance workflow** with three trigger mechanisms:

1. **Passive logging** (always on): MERAK backend and workflow event journals append
   events to `.merak/meta/events.jsonl` during normal usage. No external hook is needed.

2. **Lifecycle readiness check**: After an MERAK workflow run or chat session closes,
   the MERAK coordinator may run `check_ready.sh` (or the equivalent backend check).
   It counts skill invocations since the last `/meta-optimize` run. If ≥5 new
   invocations have accumulated, it emits a reminder through the native event stream:
   ```
   📊 MERAK has logged 8 skill runs since last optimization. Run /meta-optimize to check for improvement opportunities.
   ```
   This is a **suggestion only** — it does not auto-run optimization.

3. **Manual trigger**: User runs `/meta-optimize` when they see the reminder or whenever they want.

**After each `/meta-optimize` run**, the skill writes the current timestamp to `.merak/meta/.last_optimize` so the readiness check only counts new invocations.

## Acknowledgements

Inspired by [Meta-Harness](https://arxiv.org/abs/2603.28052) (Lee et al., 2026) — end-to-end optimization of model harnesses via filesystem-based experience access and agentic code search.

## Output Protocols

> Follow these shared protocols for all output files:
> - **[Output Versioning Protocol](../shared-references/output-versioning.md)** — write directly to the canonical fixed path; no copying or path migration
> - **[Output Manifest Protocol](../shared-references/output-manifest.md)** — log every output to MANIFEST.md
> - **[Output Language Protocol](../shared-references/output-language.md)** — respect the project's language setting

## Review Tracing

After each `reviewer_api` or `reviewer_api_reply` reviewer call, save the trace following `shared-references/review-tracing.md` (Policy C — forensic; never silently skip). Use `save_trace.sh` (resolved per the chain in `shared-references/integration-contract.md` §2) or write files directly to `.merak/traces/<skill>/<date>_run<NN>/`. Respect the `--- trace:` parameter (default: `full`).
