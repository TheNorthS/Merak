# Research Chat Agent Design

## Product Role

The chat panel is a research artifact copilot. It is used after MERAK workflows generate papers, experiment code, slides, figures, literature notes, and idea documents. It must not behave as a generic IDE source editor. All file access and edits stay inside `paper/`, `slides/`, `experiments/`, `figures/`, `literature/`, and `ideas/` unless a user explicitly moves to another workflow surface.

## Research Goal Alignment

Every editing or writing action is checked against project memory before producing a change proposal. The memory source is `.merak/memory.json` and its readable mirror `.merak/CONTEXT.md`; it stores the research direction, workflow history, key decisions, and recent findings. The agent treats the research direction, core hypothesis, contribution boundary, experiment protocol, metric definitions, and paper narrative as hard context.

If a request may change a claim, dataset split, metric meaning, experiment conclusion, section semantics, or figure evidence, the agent must report drift risk and ask for confirmation before proposing a file change. Routine wording, formatting, typo fixes, and local code cleanups can proceed directly as approval-gated proposals.

## Conversation Memory Model

The UI keeps visible chat history for the current project in `.merak/chat/conversations.json`; `localStorage` is only a temporary fallback. The backend keeps live model sessions in memory for fast multi-turn continuity. When the backend session is lost, the frontend sends a compact recent-history payload so the backend can rebuild the task context without replaying the entire chat.

History is separated into these layers:

1. Project memory: stable research direction and accepted decisions.
2. Conversation summary: older turns compressed into decisions, rejected paths, and unresolved questions.
3. Recent turns: last user/assistant messages, including proposal status.
4. Artifact context: current file and explicitly attached files.
5. Tool evidence: reads, grep results, compile logs, and generated proposal metadata.

Only approved changes become facts. Pending or rejected proposals remain evidence, not source truth.

## Context Packing Policy

Context is packed by priority: system boundaries, research goal memory, current task, explicit user-selected files, current active artifact, recent turns, compressed older turns, then optional tool evidence. Explicit attachments always outrank automatic context. Switching modes or active files creates a fresh backend context key, preventing stale experiment code from leaking into a paper review.

Long files are compressed by artifact type. Python keeps imports, class/function indexes, and important excerpts. LaTeX keeps section indexes plus beginning/end excerpts. Markdown keeps heading indexes. YAML/JSON/TOML keep the front matter and key configuration region. This reduces model timeouts and keeps reasoning anchored to structure instead of raw file dumps.

## Human Approval Boundary

`Edit` and `Write` never write files directly. They create change proposals with target path, diff, and status. The UI applies the diff only after the user approves it. After approval, open editor tabs are refreshed from disk so the visible artifact matches the accepted file state.

## Mode Contracts

`Ask` explains and compares without edits. `Edit` produces narrow approval-gated diffs. `Review` audits claims, code, citations, and reproducibility without editing. `Write` drafts or extends research artifacts with approval. `Figure` creates or improves figure artifacts under `figures/`.

Each mode must show agent activity separately from the final answer. Tool calls, retries, model fallback, and proposal generation belong in activity. User-facing conclusions, drift risks, and approved next steps belong in the final answer.

## Model Compatibility

The agent protocol is provider-neutral. It uses OpenAI-compatible messages, optional tool definitions, streaming text when tools are disabled, and retry/fallback for transient 429/503/timeout failures. Provider-specific behavior is isolated in the model router so future Claude, GLM, DeepSeek, Qwen, Gemini, or local OpenAI-compatible pools can share the same chat UX.

## UI Requirements

The panel must support long-chain research discussion: resizable width, bounded message layout, wrapped code blocks with visible copy controls, persistent sessions, explicit file attachments, and an auto-growing composer. Long user input grows up to a fixed height and then scrolls internally without hiding the top of the draft or covering action buttons.
## Completed workflows

Completed runs retain their status and acceptance history. Approved sidebar edits create separate local revisions, with the original delivery and pre-edit bytes preserved. They never schedule workflow nodes; further execution requires an explicit user action. Closing the panel preserves its mounted session and input draft.
