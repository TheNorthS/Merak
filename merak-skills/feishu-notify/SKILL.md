---
name: feishu-notify
description: "Send notifications to Feishu/Lark. Internal utility used by other skills, or manually via /feishu-notify. Use when user says \"发飞书\", \"notify feishu\", or other skills need to send status updates."
argument-hint: [message-text]
allowed-tools: Read
---

# Feishu/Lark Notification

Send a notification: **$ARGUMENTS**

## Overview

This skill provides Feishu/Lark integration for MERAK. It is designed as an **internal utility** — other skills call it at key events (experiment done, review scored, checkpoint waiting). It can also be invoked manually.

**Zero-impact guarantee**: If the MERAK Feishu channel is not configured,
enabled, and delivery-verified, this skill does nothing and returns silently.
All workflows remain usable without Feishu.

## Configuration

Configure Feishu in **MERAK Settings → Notifications**, test delivery, then
enable the channel. The backend persists the secret and exposes only redacted
status through `GET /api/notify/config`. A server deployment may alternatively
set `FEISHU_WEBHOOK_URL` in the MERAK backend environment.

This skill never reads a coding-agent settings directory, never asks the model
to handle the webhook secret, and never writes a second notification config.

### Modes

| Mode | MERAK state | What it does | Requires |
|------|------------|--------------|----------|
| **Off** | Channel absent, disabled, or unverified | No-op | Nothing |
| **Push only** | Feishu channel enabled | Send webhook cards at key events | Verified Feishu bot webhook |
| **Checkpoint** | Feishu enabled + MERAK UI connected | Push the checkpoint to Feishu; collect the answer in MERAK over its native workflow WebSocket | Verified webhook and an MERAK web/Electron client |

## Workflow

### Step 1: Resolve Native Channel State

Use the MERAK notification service's server-side state:

- **Not configured, disabled, or unverified** → return silently
- **Enabled and verified** → proceed to Step 2
- Never request or print the stored webhook URL

### Step 2: Push Notification (native webhook service)

Submit `title`, `content`, `level`, event metadata, and
`channel=feishu` to MERAK's `notification_service`. The backend constructs
the rich card and sends it with its managed HTTP client. Skills must not call
the webhook directly.

**Card templates by event type:**

| Event | Title | Color | Body |
|-------|-------|-------|------|
| `experiment_done` | Experiment Complete | `green` | Results table, delta vs baseline |
| `review_scored` | Review Round N: X/10 | `blue` (≥6) / `orange` (<6) | Score, verdict, top 3 weaknesses |
| `checkpoint` | Checkpoint: Waiting for Input | `yellow` | Question, options, context |
| `error` | Error: [type] | `red` | Error message, what failed |
| `pipeline_done` | Pipeline Complete | `purple` | Final summary, deliverables |
| `custom` | Custom | `blue` | Free-form message from $ARGUMENTS |

**Return immediately after dispatch** — push mode never waits for a response.

### Step 3: Checkpoint Notification (MERAK WebSocket)

Feishu delivery is outbound notification only. For a checkpoint:

1. Dispatch the checkpoint card through the native Feishu webhook service.
2. Publish the question and options through MERAK's workflow question channel.
3. Wait for the answer on the existing MERAK workflow WebSocket.
4. On timeout or client disconnect, apply the calling workflow's
   `AUTO_PROCEED` policy.
5. Return the MERAK UI answer to the calling skill.

Do not start, poll, or depend on an external bridge process.

### Step 4: Verify Delivery

- **Push mode**: Inspect the native service result. Log delivery failure but do
  not block the workflow.
- **Checkpoint mode**: A WebSocket timeout affects only the question policy;
  it does not cause repeated webhook sends.

## Helper Function (for other skills)

Other skills should use this pattern to send notifications:

```markdown
### Feishu Notification (if configured)

Ask the MERAK notification service for the redacted Feishu channel state:
- If **enabled and verified**: dispatch the event through the native service
- If a user answer is required: ask through the MERAK workflow WebSocket
- Otherwise: skip entirely (no-op)
```

**This check is always guarded.** Missing, disabled, or unverified channel
state skips the notification block with no secret exposure.

## Event Catalog

Skills send these events at these moments:

| Skill | Event | When |
|-------|-------|------|
| `/auto-review-loop` | `review_scored` | After each round's review score |
| `/auto-review-loop` | `pipeline_done` | Loop complete (positive or max rounds) |
| `/auto-paper-improvement-loop` | `review_scored` | After each round's review score |
| `/auto-paper-improvement-loop` | `pipeline_done` | All rounds complete |
| `/run-experiment` | `experiment_done` | Screen session finishes |
| `/idea-discovery` | `checkpoint` | Between phases (if interactive) |
| `/idea-discovery` | `pipeline_done` | Final report ready |
| `/monitor-experiment` | `experiment_done` | Results collected |
| `/research-pipeline` | `checkpoint` | Between workflow stages |
| `/research-pipeline` | `pipeline_done` | Full pipeline complete |

## Key Rules

- **NEVER block a workflow** because Feishu is unreachable. Always fail open.
- **NEVER require Feishu config** — all skills must work without it.
- **Unavailable native channel = mode off.** No error and no workflow failure.
- **Push mode is fire-and-forget.** Dispatch once and move on.
- **WebSocket checkpoint timeout = auto-proceed.** Do not hang forever.
- **Respect `AUTO_PROCEED`**: If the user does not answer in the MERAK client
  before timeout, use the calling skill's normal default.
- **No secrets in notifications.** Never include API keys, tokens, or passwords in Feishu messages.
