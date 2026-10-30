---
name: auto-review-loop-minimax
description: Compatibility entry point for the autonomous review loop when the MERAK Reviewer route is configured to a MiniMax API endpoint. Uses the native model API adapter; no external CLI or MCP server is required.
argument-hint: [topic-or-scope]
allowed-tools: Read, Grep, Glob, Write, Edit, Skill, reviewer_api, reviewer_api_reply
---

# Auto Review Loop — MiniMax through MERAK Model API

This command preserves the historical `/auto-review-loop-minimax` entry point
without maintaining a second transport implementation.

## Context: $ARGUMENTS

## Configuration

Configure an OpenAI-compatible Reviewer provider in **MERAK Settings → Models**:

- base URL: the official or researcher-approved MiniMax API endpoint;
- API key: stored in the MERAK settings/configuration layer or
  `MINIMAX_API_KEY` server environment variable;
- model: the selected MiniMax review-capable model.

Do not read coding-agent settings files, register an external server, or issue a
raw shell HTTP request from this skill.

## Preflight

1. Resolve `ModelRole.EXECUTOR` and `ModelRole.REVIEWER`.
2. Require the Reviewer route to resolve to the configured MiniMax endpoint and
   concrete model identity.
3. Require the Reviewer identity to differ from the Executor identity.
4. Run the native MERAK connection verification. Stop with `BLOCKED` when any
   check fails.

The stable `reviewer_api` and
`reviewer_api_reply` names are MERAK native API tool IDs only;
they do not select a Codex installation or start an MCP process.

## Delegation

Invoke the canonical loop:

```text
/auto-review-loop "$ARGUMENTS" — reviewer: model-api
```

Preserve any supported `compact`, `human checkpoint`, `difficulty`, and
`render html` arguments.

## Required behavior

- Maximum four rounds unless the user explicitly supplies a bounded override.
- Stop only when score >= 6 and verdict is `ready` or `almost`.
- Preserve the full raw response, provider/model identity, and evidence hashes.
- Implement fixes before re-review.
- Persist `review-stage/REVIEW_STATE.json` after every round.
- Save forensic traces under
  `.merak/traces/auto-review-loop-minimax/`.
- Never fall back to the Executor, a deterministic score, or an unverified
  transport when the MiniMax Reviewer API is unavailable.
