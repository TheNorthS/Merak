"""Bounded model execution for prepared research specialist subnodes."""

from __future__ import annotations

import time
import os
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional


EmitFn = Callable[[str, dict[str, Any]], Awaitable[None]]


class SpecialistExecutor:
    def __init__(
        self,
        service: Any,
        root: Path,
        run_id: str,
        node_id: str,
        direction: str,
        payload: dict[str, Any],
        emit: Optional[EmitFn],
    ) -> None:
        self.service = service
        self.root = root
        self.run_id = run_id
        self.node_id = node_id
        self.direction = direction
        self.payload = payload
        self.profile = dict(payload.get("profile") or {})
        self.emit = emit

    async def execute(self) -> list[dict[str, Any]]:
        entries = [
            item for item in self.payload.get("subnodes", [])
            if isinstance(item, dict) and item.get("node_id") == self.node_id
        ]
        for entry in entries:
            await self._execute_entry(entry)
        return entries

    def _entry_is_current(self, entry: dict[str, Any]) -> bool:
        valid, _ = self.service._artifact_valid(self.root, entry)
        if entry.get("status") == "completed":
            execution_valid = self.service._invocation_trace_valid(self.root, entry)[0]
        elif entry.get("status") == "reused":
            execution_valid = bool(str(entry.get("reused_from_run") or "").strip())
        else:
            execution_valid = False
        return bool(entry.get("status") in {"completed", "reused"} and valid and execution_valid)

    async def _emit(self, event: str, entry: dict[str, Any], **extra: Any) -> None:
        if not self.emit:
            return
        await self.emit(event, {
            "node_id": self.node_id,
            "subnode_id": entry["id"],
            "name": entry["name"],
            "skill": entry["skill"],
            "artifact": entry["artifact"],
            **extra,
        })

    def _persist(self) -> None:
        self.service._atomic_write(
            self.service.plan_path(self.root, self.run_id), self.payload
        )

    async def _start_entry(self, entry: dict[str, Any]) -> None:
        from .skill_orchestrator import skill_orchestrator

        entry.update({"status": "running", "started_at": time.time()})
        self._persist()
        skill_orchestrator.mark_execution(
            str(self.root), self.run_id, self.node_id, str(entry["skill"]),
            "running", role="profile_specialist", policy_loaded=True,
            execution_kind="model_owned",
        )
        await self._emit("specialist_node_started", entry, profile=self.profile)

    def _arguments(self, entry: dict[str, Any]) -> tuple[str, str]:
        headings = "\n".join(
            f"- {heading}" for heading in entry.get("required_headings") or []
        )
        inputs = [
            self.root / relative
            for relative in self.service._input_relatives(self.node_id)
            if (self.root / relative).is_file()
        ]
        input_lines = "\n".join(f"- {path}" for path in inputs) or "- No canonical inputs currently exist."
        arguments = f"""Execute this specialist subnode for the current research profile.

Research direction: {self.direction}
Research family: {self.profile.get('family')}
Study archetype: {self.profile.get('study_archetype')}
Target venue: {self.profile.get('target_venue')}
Evidence mode: {self.profile.get('evidence_mode') or 'design_only'}
Canonical output: {self.root / str(entry['artifact'])}
Purpose: {entry['purpose']}

Required headings or content markers:
{headings}

Canonical inputs currently present:
{input_lines}

Read the listed canonical inputs before writing. Write only the canonical artifact.
Do not invent observations, sample sizes, approvals, metrics, citations, or completed validation.
In a non-executed evidence mode, produce a runnable plan and mark evidence as pending.
Return only after the file exists and you have re-read it.
"""
        contract = (
            f"Macro stage: {self.node_id}\nDynamic subnode: {entry['id']}\n"
            f"This invocation owns only {entry['artifact']}. It must not rewrite the "
            "selected idea, main paper, result files, or unrelated specialist artifacts."
        )
        return arguments, contract

    def _event_callback(self, entry: dict[str, Any]) -> Callable[[Any], Awaitable[None]]:
        async def on_event(event: Any) -> None:
            if not self.emit or event.type != "status":
                return
            data = event.data if isinstance(event.data, dict) else {}
            from ..workflows.model_progress_fields import model_progress_fields
            await self._emit(
                "specialist_node_progress", entry,
                status=str(data.get("status") or "running"),
                provider=str(data.get("provider") or ""),
                model=str(data.get("model") or ""),
                **model_progress_fields(data),
            )
        return on_event

    def _trace(self, entry: dict[str, Any], started_at: float) -> dict[str, Any]:
        return self.service._latest_invocation_trace(
            self.root, str(entry["skill"]), started_at
        )

    async def _complete(self, entry: dict[str, Any], trace: dict[str, Any], result: Any) -> None:
        from .skill_orchestrator import skill_orchestrator

        entry.update({
            "status": "completed", "completed_at": time.time(),
            "artifact_sha256": self.service._sha256(self.root / str(entry["artifact"])),
            "session_id": str(trace.get("session_id") or ""),
            "model_provider": str(trace.get("model_provider") or ""),
            "model_name": str(trace.get("model_name") or ""),
            "invocation_trace": str(trace.get("trace_path") or ""),
        })
        skill_orchestrator.mark_execution(
            str(self.root), self.run_id, self.node_id, str(entry["skill"]),
            "completed", role="profile_specialist",
            session_id=entry["session_id"], output=result, policy_loaded=True,
            execution_kind="model_owned", model_provider=entry["model_provider"],
            model_name=entry["model_name"],
        )
        await self._emit("specialist_node_completed", entry, session_id=entry["session_id"])


    async def _fail(
        self,
        entry: dict[str, Any],
        trace: dict[str, Any],
        error: Exception,
    ) -> None:
        from .skill_orchestrator import skill_orchestrator

        entry.update({
            "status": "failed", "finished_at": time.time(), "error": str(error)[:2000],
            "session_id": str(trace.get("session_id") or ""),
            "model_provider": str(trace.get("model_provider") or ""),
            "model_name": str(trace.get("model_name") or ""),
            "invocation_trace": str(trace.get("trace_path") or ""),
        })
        skill_orchestrator.mark_execution(
            str(self.root), self.run_id, self.node_id, str(entry["skill"]),
            "failed", role="profile_specialist", session_id=entry["session_id"],
            error=str(error), policy_loaded=True, execution_kind="model_owned",
            model_provider=entry["model_provider"], model_name=entry["model_name"],
        )
        await self._emit("specialist_node_failed", entry, error=str(error)[:500])
        self._persist()

    async def _execute_entry(self, entry: dict[str, Any]) -> None:
        from ..agent.tools import invoke_skill

        if self._entry_is_current(entry):
            await self._emit("specialist_node_reused", entry)
            return
        await self._start_entry(entry)
        arguments, contract = self._arguments(entry)
        started_at = time.time()
        try:
            result = await invoke_skill(
                str(entry["skill"]), arguments, project_path=str(self.root),
                parent_context=f"skill-chain:workflow>{self.node_id}",
                on_event=self._event_callback(entry),
                allowed_tools_override=["Read", "Write", "Edit", "Glob", "Grep"],
                invocation_contract=contract, max_iterations=14,
            )
            valid, issues = self.service._artifact_valid(self.root, entry)
            if not valid:
                raise RuntimeError("; ".join(issues))
            await self._complete(entry, self._trace(entry, started_at), result)
        except Exception as exc:
            trace = self._trace(entry, started_at)
            await self._fail(entry, trace, exc)
            raise
        self._persist()


async def execute_specialists_for_node(
    service: Any,
    project_path: str | Path,
    run_id: str,
    node_id: str,
    direction: str,
    options: dict[str, Any],
    selected_node_ids: list[str] | set[str] | tuple[str, ...],
    emit: Optional[EmitFn],
) -> list[dict[str, Any]]:
    from .skill_registry import skill_registry

    root = Path(project_path).expanduser().resolve()
    if not skill_registry.get_skill("domain-methodology"):
        skill_registry.scan_directory(
            Path(os.environ.get("MERAK_SKILLS_PATH") or Path(__file__).parents[2] / "merak-skills")
        )
    payload = service.prepare(root, run_id, direction, options, selected_node_ids)
    return await SpecialistExecutor(
        service, root, run_id, node_id, direction, payload, emit
    ).execute()
