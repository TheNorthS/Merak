"""Human-readable display projection for durable workflow events."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Callable


Compact = Callable[[Any, int], str]
UNHANDLED = object()


def _agent_event(
    event: str,
    data: dict[str, Any],
    compact: Compact,
) -> tuple[str, str, str] | None | object:
    if event == "agent_output":
        return "Agent", "agent", compact(data.get("text"), 1200)
    if event in {"agent_tool_call", "agent_tool_result", "agent_step"}:
        if data.get("paper_stage"):
            return None
        if event == "agent_tool_call":
            tool, args = compact(data.get("tool"), 100), compact(data.get("args"), 500)
            return "Tool", "tool", f"{tool}({args})" if args else tool
        if event == "agent_tool_result":
            tool = compact(data.get("tool"), 100)
            output = compact(data.get("output"), 700)
            prefix = "↩" if data.get("success", True) else "✗"
            return "Tool", "tool", f"{prefix} {tool}: {output}".rstrip()
        return "Agent", "agent", compact(
            data.get("message") or data.get("description") or data.get("step"), 1200
        )
    if event == "agent_status":
        if data.get("status") == "iteration_budget":
            return "System", "warn", f"本轮模型步骤剩余 {data.get('iterations_remaining')}，即将转入产物验收。"
        if data.get("status") == "retrying_provider":
            return "System", "warn", f"模型请求重试 {data.get('next_attempt', data.get('attempt'))}/{data.get('max_attempts')}；{data.get('retry_in_seconds')}s 后重试，总预算剩余 {data.get('remaining_seconds')}s"
        if data.get("status") in {"waiting_model", "streaming_model"}:
            action = "正在接收模型输出" if data["status"] == "streaming_model" else "等待模型响应"
            remaining = data.get("attempt_remaining_seconds", data.get("remaining_seconds", "?"))
            return "System", "info", f"{action}：本次 {data.get('elapsed', 0)}s，第 {data.get('attempt', 1)}/{data.get('max_attempts', 1)} 次尝试，本次截止剩余 {remaining}s，总预算剩余 {data.get('remaining_seconds', '?')}s"
        return "Agent", "agent", compact(data.get("status"), 1200)
    if event == "agent_error":
        return "Agent", "error", compact(data.get("error"), 1200)
    return UNHANDLED


def _implementation_event(
    event: str,
    data: dict[str, Any],
    compact: Compact,
) -> tuple[str, str, str] | object:
    if event == "implementation_stage_budget_exhausted":
        return "System", "warn", f"实验实现阶段 {compact(data.get('stage_id'), 80)}：步骤预算已用完，正在验收已保存文件。"
    if event == "implementation_stage_progress" and data.get("status") in {"waiting_model", "streaming_model", "retrying_provider", "iteration_budget"}:
        request = data.get("model_request")
        request = request if isinstance(request, dict) else {}
        source, level, message = _agent_event("agent_status", {**request, "status": data["status"]}, compact)
        return source, level, f"实验实现阶段 {compact(data.get('stage_id'), 80)}：{message}"
    supported = {
        "implementation_stage_started", "implementation_stage_accepted",
        "implementation_stage_needs_revision", "implementation_stage_reused",
    }
    if event not in supported:
        return UNHANDLED
    stage = compact(data.get("stage_id"), 80)
    title = compact(data.get("title") or stage, 160)
    attempt, maximum = compact(data.get("attempt"), 20), compact(data.get("max_attempts"), 20)
    suffix = f"（尝试 {attempt}/{maximum}）" if attempt and maximum else (
        f"（尝试 {attempt}）" if attempt else ""
    )
    if event == "implementation_stage_started":
        return "Agent", "agent", f"实验实现阶段 {stage}：开始 {title}{suffix}"
    if event == "implementation_stage_accepted":
        return "Agent", "info", f"实验实现阶段 {stage}：验收通过{suffix}"
    if event == "implementation_stage_reused":
        return "Agent", "info", f"实验实现阶段 {stage}：复用已验收产物"
    issues = data.get("issues")
    issue = compact(issues[0], 600) if isinstance(issues, list) and issues else compact(data.get("message"), 600)
    message = f"实验实现阶段 {stage}：需要修订{suffix}"
    return "Agent", "warn", message + (f"；{issue}" if issue else "")


def _node_event(
    event: str,
    data: dict[str, Any],
    compact: Compact,
    node_id: str,
    name: str,
) -> tuple[str, str, str] | object:
    if event == "node_started":
        return "System", "info", f"Running: {name}"
    if event == "node_revalidating":
        return "System", "info", f"Revalidating: {name}"
    if event == "node_dependency_reused":
        dependency = compact(data.get("dependency_id"), 80)
        return "System", "info", f"{node_id} 已复用并重新验收现存上游产物：{dependency}"
    if event == "node_completed":
        duration = data.get("duration")
        suffix = f" ({float(duration) / 60:.1f}min)" if isinstance(duration, (int, float)) else ""
        return "Agent", "agent", f"{name or node_id} 执行阶段结束{suffix}，尚未通过验收"
    if event == "node_accepted":
        reviewer = compact(data.get("reviewer"), 160)
        return "Agent", "agent", f"✓ {node_id} accepted" + (f" by {reviewer}" if reviewer else "")
    if event == "node_skipped":
        return "System", "warn", f"Skipped {node_id}: {compact(data.get('reason'), 500)}"
    if event in {"node_failed", "workflow_error"}:
        return "System", "error", compact(data.get("error") or data.get("summary"), 1200)
    if event == "node_quality_advisory":
        return "System", "warn", compact(data.get("plain_message") or data.get("message") or data.get("summary"), 1200)
    return UNHANDLED


def _workflow_event(
    event: str,
    data: dict[str, Any],
    compact: Compact,
) -> tuple[str, str, str] | object:
    if event == "workflow_failed":
        failed = ", ".join(str(item) for item in data.get("failed_nodes", []))
        return "System", "error", f"Workflow failed: {failed or 'unfinished node'}; checkpoint preserved"
    if event == "workflow_incomplete":
        pending = ", ".join(str(item) for item in data.get("pending_nodes", []))
        return "System", "warn", f"Workflow attempt ended; resumable nodes: {pending}"
    if event == "workflow_cancelled":
        return "System", "warn", "Workflow cancelled"
    if event != "workflow_completed":
        return UNHANDLED
    messages = {
        "reviewable_draft_ready": "Workflow completed: reviewable scientific draft; research limitations retained, not approved for submission",
        "submission_ready": "Workflow completed: submission candidate passed the configured evidence gates",
        "synthetic_preview_ready": "Workflow completed: deterministic benchmark manuscript ready as a complete submission track",
        "protocol_ready": "Workflow completed: research protocol draft ready; experiments remain pending",
        "evidence_blocked": "Workflow completed: manuscript built, but submission evidence is blocked",
        "partial_workflow_complete": "Selected workflow phases completed; full submission pipeline was not run",
    }
    completion = compact(data.get("completion_class"), 80)
    return "System", "info", messages.get(
        completion, compact(data.get("label"), 160) or "Workflow completed"
    )


def _revision_event(
    event: str,
    data: dict[str, Any],
    compact: Compact,
    node_id: str,
) -> tuple[str, str, str] | object:
    if event == "node_revision_started":
        return "Agent", "agent", f"{node_id} automatic revision {data.get('round', 0)}/{data.get('max_revision_rounds', 0)}"
    if event == "node_revision_completed":
        return "Agent", "agent", f"{node_id} revision {data.get('round', 0)} updated its target artifact; revalidating"
    if event == "node_revision_no_progress":
        fallback = f"{node_id} revision {data.get('round', 0)} produced no target-artifact or semantic change; revalidating"
        return "System", "warn", compact(data.get("summary") or fallback, 1200)
    if event == "node_revision_gate":
        accepted = bool(data.get("accepted"))
        summary = compact(data.get("summary") or data.get("reason"), 900)
        message = f"{node_id} quality gate {'passed' if accepted else 'needs revision'}"
        return "System", "info" if accepted else "warn", message + (f": {summary}" if summary else "")
    if event in {"node_revision_waiting", "node_platform_repair_required"}:
        level = "warn" if event == "node_revision_waiting" else "error"
        return "System", level, compact(data.get("summary") or data.get("reason"), 1200)
    return UNHANDLED


def _paper_event(
    event: str,
    data: dict[str, Any],
    compact: Compact,
) -> tuple[str, str, str] | None | object:
    stage = compact(data.get("stage_label") or data.get("stage_id"), 160)
    index, total = compact(data.get("stage_index"), 20), compact(data.get("stage_total"), 20)
    progress = f"{index}/{total}" if index and total else stage
    if event == "paper_stage_started":
        attempt = compact(data.get("attempt"), 20)
        return "Agent", "agent", f"论文分章 {progress}：开始 {stage}（第 {attempt or '?'} 次尝试）"
    if event == "paper_stage_reused":
        return "Agent", "info", f"论文分章 {progress}：复用已验收的 {stage}"
    if event == "paper_stage_reviewed":
        passed = bool(data.get("passed"))
        issues = data.get("issues")
        first = compact(issues[0], 500) if isinstance(issues, list) and issues else ""
        message = f"论文分章 {progress}：{stage} {'验收通过' if passed else '需要局部修订'}"
        return "Agent", "info" if passed else "warn", message + (f"：{first}" if first and not passed else "")
    if event == "paper_stage_agent_status":
        status = compact(data.get("status") or "running", 80)
        if status in {"waiting_model", "retrying_provider"}:
            action = "等待模型响应" if status == "waiting_model" else "模型请求重试"
            return "System", "info" if status == "waiting_model" else "warn", (
                f"论文分章 {stage}：{action}，本次 {data.get('elapsed', 0)}s，"
                f"第 {data.get('next_attempt', data.get('attempt', '?'))}/{data.get('max_attempts', '?')} 次请求，"
                f"总预算剩余 {data.get('remaining_seconds', '?')}s")
        if status not in {"switching_provider", "partial_stream_recovered"}:
            return None
        message = f"论文分章 {stage}：切换模型" if status == "switching_provider" else f"论文分章 {stage}：流式连接中断，已保留输出并继续"
        provider = compact(data.get("provider"), 100)
        return "Agent", "info", message + (f"（{provider}）" if provider else "")
    if event == "paper_stage_repair_skipped":
        reason = compact(data.get("reason"), 500)
        return "System", "warn", f"论文分章 {stage} 未调用模型" + (f"：{reason}" if reason else "")
    if event == "skill_invocation_revision_required":
        issues = data.get("issues")
        first = compact(issues[0], 600) if isinstance(issues, list) and issues else ""
        message = f"论文分章停在 {stage}：已保留已通过章节，等待当前章节修订"
        return "System", "warn", message + (f"；{first}" if first else "")
    return UNHANDLED


def _misc_event(
    event: str,
    data: dict[str, Any],
    compact: Compact,
    node_id: str,
) -> tuple[str, str, str] | object:
    if event == "specialist_node_progress" and data.get("status") in {"waiting_model", "retrying_provider"}:
        retry = data["status"] == "retrying_provider"
        name = compact(data.get("name") or data.get("subnode_id"), 120)
        action = "模型请求重试" if retry else "等待模型响应"
        return "System", "warn" if retry else "info", (
            f"专家子节点 {name}：{action}，本次 {data.get('elapsed', 0)}s，"
            f"第 {data.get('next_attempt', data.get('attempt', '?'))}/{data.get('max_attempts', '?')} 次请求，"
            f"总预算剩余 {data.get('remaining_seconds', '?')}s")
    if event == "skill_dispatch_started":
        skill = compact(data.get("skill"), 160)
        return "System", "info", f"{node_id} 已进入分章调度" + (f"：/{skill}" if skill else "")
    if event in {"checkpoint_waiting", "checkpoint_extended", "checkpoint_resumed", "checkpoint_auto_resumed"}:
        level = "warn" if event == "checkpoint_waiting" else "info"
        message = data.get("message") or data.get("summary") or f"{event.replace('_', ' ')}: {node_id}"
        return "System", level, compact(message, 1200)
    if event in {"experiment_log", "experiment_phase", "experiment_anomaly", "experiment_failed", "experiment_finished"}:
        level = "error" if event in {"experiment_anomaly", "experiment_failed"} else "info"
        message = data.get("line") or data.get("message") or data.get("error") or data.get("phase") or data.get("status")
        return "System", level, compact(message, 1200)
    if event in {"skill_invocation_failed", "figure_artifact_failed", "node_revision_error"}:
        return "System", "error", compact(data.get("error") or data.get("summary") or data.get("reason"), 1200)
    if event in {"skill_invocation_started", "skill_invocation_completed", "skill_invocation_reused"}:
        skill = compact(data.get("skill") or data.get("skill_name"), 120)
        return "Agent", "agent", event.replace("_", " ") + (f": /{skill.lstrip('/')}" if skill else "")
    if event in {"node_recovered", "paper_plan_artifact_recovered", "narrative_artifact_recovered"}:
        level = "warn" if event == "node_recovered" else "info"
        return "System", level, compact(data.get("message") or data.get("reason") or data.get("path"), 1200)
    explicit = data.get("message") or data.get("warning")
    return ("System", "info", compact(explicit, 1200)) if explicit else UNHANDLED


def format_display_entry(
    event: str,
    data: dict[str, Any],
    compact: Compact,
    timestamp: float | None = None,
) -> dict[str, str] | None:
    node_id = compact(data.get("node_id"), 80)
    name = compact(data.get("name") or node_id, 120)
    formatters = (
        lambda: _agent_event(event, data, compact),
        lambda: _implementation_event(event, data, compact),
        lambda: _node_event(event, data, compact, node_id, name),
        lambda: _workflow_event(event, data, compact),
        lambda: _revision_event(event, data, compact, node_id),
        lambda: _paper_event(event, data, compact),
        lambda: _misc_event(event, data, compact, node_id),
    )
    result: tuple[str, str, str] | None | object = UNHANDLED
    for formatter in formatters:
        result = formatter()
        if result is not UNHANDLED:
            break
    if result is None or result is UNHANDLED:
        return None
    source, level, message = result
    if not message:
        return None
    try:
        occurred_at = datetime.fromtimestamp(timestamp) if timestamp is not None else datetime.now()
    except (OSError, OverflowError, TypeError, ValueError):
        occurred_at = datetime.now()
    return {
        "time": occurred_at.strftime("%H:%M:%S"),
        "source": source,
        "message": message,
        "level": level,
    }
