"""Isolated and auditable MERAK skill invocation tool."""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from ...utils.atomic_write import atomic_write_json


@dataclass(frozen=True)
class LoadedSkill:
    name: str
    metadata: Any
    source: Path
    source_bytes: bytes
    policy: str
    root: Path
    lineage: list[str]
    orchestrator: Any


def _load_skill(
    skill_name: str, project_path: str, parent_context: str,
) -> LoadedSkill:
    from server.services.skill_registry import normalize_skill_runtime_contract, skill_registry
    from server.services.artifact_contract import validate_skill_artifact_contract_content
    from server.services.skill_orchestrator import skill_orchestrator

    name = skill_name.lstrip("/")
    metadata = skill_registry.get_skill(name)
    if not metadata or not metadata.file_path:
        raise ValueError(f"Unknown MERAK skill: {name}")
    source = Path(metadata.file_path).resolve()
    source_bytes = source.read_bytes()
    raw = source_bytes.decode(encoding="utf-8", errors="replace").strip()
    validate_skill_artifact_contract_content(raw)
    policy = normalize_skill_runtime_contract(skill_orchestrator.full_policy(name) or raw)
    if not policy:
        raise ValueError(f"MERAK skill is empty: {name}")
    root = Path(project_path or ".").expanduser().resolve()
    lineage = [
        item for item in str(parent_context or "").removeprefix("skill-chain:").split(">")
        if item
    ]
    if name in lineage:
        raise RuntimeError("Recursive skill invocation blocked: " + " > ".join([*lineage, name]))
    lineage.append(name)
    return LoadedSkill(
        name, metadata, source, source_bytes, policy, root, lineage,
        skill_orchestrator,
    )


def _system_prompt(loaded: LoadedSkill, invocation_contract: str) -> tuple[str, list[str]]:
    from ..prompts import MERAK_SYSTEM_PROMPT
    from ...services.artifact_contract import render_artifact_contract

    prompt = (
        MERAK_SYSTEM_PROMPT + "\n\n## Loaded MERAK Skill Invocation\n"
        f"Skill: /{loaded.name}\nInvocation mode: isolated delegate\n"
        "The complete SKILL.md below is the executable contract for this session. "
        "Perform its work and create its declared artifact; do not merely summarize "
        "the instructions. Nested Skill and Agent delegation are disabled.\n\n"
        + loaded.policy + f"\n\n## Canonical project root\n{loaded.root}\n"
        "Resolve relative research-artifact paths against this root. Do not modify "
        "the Merak source tree or any SKILL.md file."
    )
    if loaded.metadata.artifact_contracts:
        prompt += (
            "\n\n## Versioned artifact contract\n"
            + "\n".join(
                f"- {path}: schema={schema} (exact current version; no migration)"
                for path, schema in sorted(loaded.metadata.artifact_contracts.items())
            )
        )
    readonly_roots = loaded.orchestrator.readonly_reference_roots(loaded.name)
    if readonly_roots:
        prompt += (
            "\n\n## Verified read-only shared references\n"
            "Use these exact readable policy roots; do not infer another installation path:\n- "
            + "\n- ".join(readonly_roots)
        )
    if invocation_contract.strip():
        prompt += (
            "\n\n## Bounded workflow invocation contract\n"
            "This scopes the current invocation without replacing SKILL.md.\n"
            + invocation_contract.strip()
        )
    prompt += "\n\n" + render_artifact_contract(loaded.root)
    if loaded.name in {"domain-experiment-plan", "experiment-plan"}:
        from ...contracts.implementation_readiness import readiness_instruction
        prompt += "\n\n" + readiness_instruction()
    if loaded.metadata.output_files:
        prompt += "\nDeclared skill output paths: " + ", ".join(loaded.metadata.output_files)
    return prompt, readonly_roots


def _allowed_tools(
    loaded: LoadedSkill, engine: Any,
    override: Optional[list[str]],
) -> list[str]:
    if override is not None:
        requested = {str(name).strip() for name in override if str(name).strip()}
        allowed = [name for name in engine._tools if name in requested]
    elif loaded.metadata.allowed_tools:
        from server.services.skill_registry import skill_registry

        allowed = skill_registry.resolve_allowed_tools(loaded.name, list(engine._tools))
    else:
        allowed = [name for name in ("Read", "Write", "Edit", "Glob", "Grep") if name in engine._tools]
    from ...services.workflow_tool_capabilities import delegated_disabled_tools
    disabled = delegated_disabled_tools(str(loaded.root))
    return [
        name for name in dict.fromkeys(allowed)
        if name not in {"Skill", "Agent", "AskUserQuestion"} | disabled
    ]


def _new_trace(
    loaded: LoadedSkill, session: Any, allowed_tools: list[str],
    parent_context: str, invocation_contract: str,
) -> tuple[Path, dict[str, Any]]:
    invocation_id = uuid.uuid4().hex[:12]
    directory = loaded.root / ".merak" / "skill-invocations"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{invocation_id}_{loaded.name}.json"
    trace = {
        "schema": 1, "id": invocation_id, "skill": loaded.name,
        "role": "delegate", "status": "running", "session_id": session.id,
        "parent_context": parent_context, "project_path": str(loaded.root),
        "allowed_tools": allowed_tools,
        "allowed_write_paths": getattr(session, "allowed_write_paths", None),
        "bounded_invocation": bool(invocation_contract.strip()),
        "skill_source": str(loaded.source),
        "skill_sha256": hashlib.sha256(loaded.source_bytes).hexdigest(),
        "skill_bytes": len(loaded.source_bytes), "policy_loaded": True,
        "started_at": time.time(),
    }
    atomic_write_json(path, trace)
    return path, trace


async def _run_traced(
    engine: Any, session: Any, loaded: LoadedSkill, arguments: str,
    allowed_tools: list[str], trace_path: Path, trace: dict[str, Any], on_event: Any,
    max_tokens: int,
) -> str:
    from ..delegate_activity import parent_activity_callback
    on_event = on_event or parent_activity_callback(loaded.name)
    async def traced_event(event: Any) -> None:
        if event.type == "status" and isinstance(event.data, dict):
            provider = str(event.data.get("provider") or "").strip()
            model = str(event.data.get("model") or "").strip()
            if provider:
                trace["model_provider"] = provider
            if model:
                trace["model_name"] = model
        if on_event:
            callback_result = on_event(event)
            if inspect.isawaitable(callback_result):
                await callback_result

    message = f"Execute /{loaded.name} for the canonical project.\n\n" + (
        arguments.strip() or "Apply the skill to the current project artifacts."
    )
    if session.recovery_count:
        message = (
            "Manually resume the same interrupted stage. Inspect the current files and saved tool results. "
            "Continue unfinished work; do not replay completed writes or external jobs.\n\n" + message
        )
    try:
        result = await engine.run(
            session_id=session.id, user_message=message,
            on_event=traced_event, tools=allowed_tools,
            max_tokens=max_tokens,
        )
    except asyncio.CancelledError:
        trace.update({
            "status": "cancelled", "finished_at": time.time(),
            "error": "Parent workflow operation was cancelled or reached its deadline.",
        })
        atomic_write_json(trace_path, trace)
        raise
    except Exception as exc:
        trace.update({
            "status": "failed", "finished_at": time.time(), "error": str(exc)[:2000],
        })
        atomic_write_json(trace_path, trace)
        raise
    trace.update({
        "status": "completed", "finished_at": time.time(),
        "stop_reason": str(getattr(session, "last_stop_reason", "") or ""),
        "output_sha256": hashlib.sha256(result.encode("utf-8", errors="replace")).hexdigest(),
        "output_chars": len(result),
    })
    atomic_write_json(trace_path, trace)
    return result


async def invoke_skill(
    skill_name: str,
    arguments: str = "",
    project_path: str = "",
    parent_context: str = "",
    workflow_node_id: str = "",
    on_event: Any = None,
    allowed_tools_override: Optional[list[str]] = None,
    invocation_contract: str = "",
    max_iterations: Optional[int] = None,
    max_tokens: int = 8192,
    tool_call_limits: Optional[dict[str, int]] = None,
    allowed_write_paths: Optional[list[str]] = None,
    resume_input_fingerprint: str = "",
) -> str:
    from .. import ModelRole
    from ..engine import agent_engine

    loaded = _load_skill(skill_name, project_path, parent_context)
    from ..write_scope import normalize_allowed_write_paths

    write_scope = normalize_allowed_write_paths(loaded.root, allowed_write_paths)
    prompt, readonly_roots = _system_prompt(loaded, invocation_contract)
    if write_scope is not None:
        prompt += (
            "\n\n## Runtime-enforced exact write scope\n"
            "Only these current-stage files may be mutated. Other broad skill outputs are "
            "not outputs of this isolated invocation; treat them as read-only inputs.\n"
            + ("\n".join(f"- {path}" for path in write_scope) or "No file mutations are authorized.")
        )
    from ..skill_resume import delegate_identity, restore_delegate
    identity = delegate_identity(loaded, parent_context, invocation_contract, write_scope,
        input_fingerprint=resume_input_fingerprint)
    session = restore_delegate(agent_engine, loaded, prompt, identity)
    if session is None:
        session = agent_engine.create_session(system_prompt=prompt, role=ModelRole.EXECUTOR)
    session.project_path = str(loaded.root)
    session.readonly_roots = readonly_roots
    session.context_key = "skill-chain:" + ">".join(loaded.lineage)
    session.workflow_node_id = str(workflow_node_id or "")
    session.tool_policy = "workflow_artifacts"
    session.allowed_write_paths = write_scope
    if tool_call_limits is not None:
        if any(
            not isinstance(name, str) or not name
            or type(count) is not int or count < 1
            for name, count in tool_call_limits.items()
        ):
            raise ValueError("skill tool_call_limits require positive integer limits")
        session.tool_call_limits = {
            **session.tool_call_limits, **tool_call_limits,
        }
    limit = 40 if max_iterations is None else max(4, int(max_iterations))
    session.max_iterations = min(session.max_iterations, limit)
    allowed = _allowed_tools(loaded, agent_engine, allowed_tools_override)
    trace_path, trace = _new_trace(
        loaded, session, allowed, parent_context, invocation_contract,
    )
    trace.update(identity)
    if identity["workflow_run_id"]:
        from ...workflows.run_state import RunState
        def bind_owner_session(saved: dict) -> None:
            repair = saved.get("active_owner_revision")
            if repair and repair.get("owner_node") == workflow_node_id:
                repair["delegate_session_id"] = session.id
        RunState(str(loaded.root), identity["workflow_run_id"]).update_state(bind_owner_session)
    atomic_write_json(trace_path, trace)
    return await _run_traced(
        agent_engine, session, loaded, arguments, allowed, trace_path, trace,
        on_event, max(1024, min(32768, int(max_tokens))),
    )
