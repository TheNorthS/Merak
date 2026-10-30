# Reviewer Routing

## Default route

All automated review calls use the independent provider configured in MERAK as
`ModelRole.REVIEWER`. MERAK sends the evidence packet directly to that
provider's model API. A review skill must never discover, install, or launch a
local coding-agent executable or an external reviewer server.

The stable tool IDs `reviewer_api` and
`reviewer_api_reply` are retained only for imported-skill
the stable native interface. Inside MERAK they are implemented by
`cross_model_review` and `cross_model_review_reply`; the names do not select
a Codex installation and do not start an MCP process.

## Mandatory independence preflight

Before the first verdict-bearing call:

1. Resolve `ModelRole.EXECUTOR` and `ModelRole.REVIEWER` through the MERAK
   model router.
2. Record both provider/model identities in the trace.
3. Require a concrete Reviewer identity different from the Executor identity.
4. Fail closed when either identity is unresolved or the identities are equal.

Provider-family independence is preferred for submission gates. When exact
family metadata is unavailable, the workflow must report that limitation
instead of claiming a cross-family verdict.

## Routing logic

```text
Parse $ARGUMENTS for an optional reviewer directive.

If absent or reviewer = model-api:
    resolve the configured independent ModelRole.REVIEWER
    call the provider through the MERAK model API adapter

If reviewer = manual:
    use the native MERAK manual-review UI only when its tool is already
    registered by the running MERAK process
    do not print installation commands
    do not fall back silently to the Executor model

Any other reviewer selector:
    stop with a configuration error
    direct the user to MERAK Settings -> Models
```

Only `model-api` and `manual` are valid selectors. Any other persisted value is
unsupported and must produce a configuration error without rewriting state.

## Model-API calling convention

Start a fresh review:

```text
reviewer_api:  # stable MERAK API-adapter ID
  file_path: <absolute path to the exact review packet>
  project_path: <absolute project root>
  reviewer_prompt: <review policy>
  config: {"model_reasoning_effort": "xhigh"}
```

Continue a deliberate same-reviewer dialogue:

```text
reviewer_api_reply:  # stable MERAK API-adapter ID
  thread_id: <saved thread id>
  message: <follow-up plus exact changed evidence>
```

Fresh-review gates must start a new thread. Follow-up tools are allowed only
when the policy explicitly requires continuity, such as judging whether a
specific previously reported issue was closed.

## Evidence transport

- Local paths are not sent as instructions for a remote model to open.
- The MERAK adapter reads the declared files, validates repository boundaries,
  binds their hashes, and sends their contents through the provider API.
- Executor summaries are context, not evidence. Prefer raw manuscript,
  result, log, code, and rendered-page artifacts.
- Re-hash mutable evidence before accepting a verdict. Discard the verdict if
  the packet changed during review.
- Native image-capable providers receive rendered page images as API image
  content. Text-only reviewers must not claim a visual-layout verdict.

## Manual review

Manual review is an explicit user choice, never an automatic fallback. If the
native MERAK manual-review tool is unavailable, stop and tell the user to enable
it in MERAK Settings. The prompt and evidence packet must be substantively
identical to the model-API route, and the user must identify the reviewing
model sufficiently to check independence.

## Invariants

- Reviewer effort is `xhigh` for verdict-bearing review unless the configured
  provider does not expose that control.
- No same-identity automated verdict.
- No shell-based reviewer fallback.
- No browser-login or local-agent authentication as an API substitute.
- No silent downgrade from model review to deterministic heuristics.
- Every verdict-bearing call writes a forensic trace containing route,
  provider/model identity, evidence hashes, prompt, response, and thread ID.
- Missing Reviewer API configuration is a visible configuration error, not a
  reason to reuse the Executor.

## Skills using this contract

This contract applies to `/research-review`, `/auto-review-loop`,
`/experiment-audit`, `/proof-checker`, `/rebuttal`, `/idea-creator`,
and every other skill that produces a reviewer verdict.
