---
name: auto-review-loop-llm
description: Compatibility entry point for an autonomous review loop using the independent Reviewer model configured in MERAK. Uses the native model API route; no external CLI or MCP server is required.
argument-hint: [topic-or-scope]
allowed-tools: Read, Grep, Glob, Write, Edit, Skill, reviewer_api, reviewer_api_reply
---

# Auto Review Loop — MERAK Reviewer Model API

This skill preserves the historical `/auto-review-loop-llm` command name. Its
implementation is the native `/auto-review-loop` workflow with
`reviewer: model-api`; it must not implement a second transport stack.

## Context: $ARGUMENTS

## Route preflight

1. Resolve `ModelRole.EXECUTOR` and `ModelRole.REVIEWER` from MERAK Settings.
2. Require concrete, different provider/model identities.
3. Verify the Reviewer connection using the native MERAK connection check.
4. If any check fails, stop with a configuration error. Never reuse the
   Executor and never look for a local agent program.

The tool IDs `reviewer_api` and
`reviewer_api_reply` are the native MERAK reviewer tools.
Inside MERAK they call `cross_model_review` and
`cross_model_review_reply`, which use the configured Reviewer provider API.

## Delegation

Invoke:

```text
/auto-review-loop "$ARGUMENTS" — reviewer: model-api
```

Pass through supported loop parameters such as `compact`,
`human checkpoint`, `difficulty`, and `render html`. Do not translate
`model-api` into a provider-specific backend name.

## Required behavior

- Use the same score/verdict stop condition as `/auto-review-loop`:
  score >= 6 and verdict in `{ready, almost}`.
- Preserve the full raw reviewer response and resolved model identity.
- Bind each review to the exact artifact packet and hashes.
- Persist `review-stage/REVIEW_STATE.json` after every round.
- Implement accepted fixes before requesting another verdict.
- Keep negative results and unresolved weaknesses visible.
- Save forensic traces under `.merak/traces/auto-review-loop-llm/`.

## Configuration

Configure API keys, base URLs, and models only in **MERAK Settings → Models** or
the corresponding MERAK server environment variables. The model router supports
OpenAI-compatible providers as well as native configured providers; this skill
does not read coding-agent settings files and does not issue raw HTTP requests.

## Failure policy

- Reviewer unavailable or not independent: `BLOCKED`.
- Provider timeout or invalid schema: preserve the trace and surface the
  transport error; do not manufacture a verdict.
- Missing artifact: stop before the model call and identify the exact path.
- Existing in-progress state: resume only when its artifact hashes and route
  identity still match; otherwise start a fresh review round.
