"""Filesystem and approval policy for agent tool calls."""

from __future__ import annotations

import difflib
import json
import uuid
from pathlib import Path
from typing import Any, Callable, Optional

from . import ToolCall, ToolDefinition
from .session_models import AgentEvent, AgentSession, PendingChange, ToolResult

RESEARCH_ARTIFACT_DIRS = ("paper", "slides", "experiments", "figures", "literature", "ideas")
RESEARCH_ARTIFACT_FILES = ("NARRATIVE_REPORT.md",)
RESEARCH_ARTIFACTS_LABEL = ", ".join(f"{name}/" for name in RESEARCH_ARTIFACT_DIRS) + ", " + ", ".join(RESEARCH_ARTIFACT_FILES)


class ToolPolicyMixin:
    def _project_root(self, session: AgentSession) -> Path:
        return Path(session.project_path or ".").expanduser().resolve()

    def _is_inside(self, path: Path, root: Path) -> bool:
        try:
            path.relative_to(root)
            return True
        except ValueError:
            return False

    def _is_research_artifact_path(self, project_root: Path, target: Path) -> bool:
        if any(target == (project_root / filename).resolve() for filename in RESEARCH_ARTIFACT_FILES):
            return True
        return any(
            target == (project_root / dirname).resolve()
            or self._is_inside(target, (project_root / dirname).resolve())
            for dirname in RESEARCH_ARTIFACT_DIRS
        )

    def _blocked_tool_result(self, tool_call: ToolCall, message: str) -> ToolResult:
        return ToolResult(
            tool_call_id=tool_call.id,
            success=False,
            output=message,
            error=message,
        )

    def _tool_definition_for(self, tool_name: str) -> Optional[ToolDefinition]:
        for definition in self._tool_definitions:
            if definition.name == tool_name:
                return definition
        return None

    def _validate_tool_call(self, tool_call: ToolCall) -> Optional[ToolResult]:
        definition = self._tool_definition_for(tool_call.name)
        if not definition:
            return self._blocked_tool_result(tool_call, f"TOOL_SCHEMA_ERROR: unknown tool `{tool_call.name}`.")
        if not isinstance(tool_call.arguments, dict):
            return self._blocked_tool_result(tool_call, f"TOOL_SCHEMA_ERROR: `{tool_call.name}` arguments must be a JSON object.")
        if tool_call.arguments.get("_parse_error"):
            return self._blocked_tool_result(
                tool_call,
                f"TOOL_SCHEMA_ERROR: `{tool_call.name}` function arguments are not valid JSON. "
                "No tool was executed; resend a complete JSON object with smaller, focused content.",
            )
        from .tool_schema import argument_issues

        issues = argument_issues(definition.parameters, tool_call.arguments)
        if issues:
            return self._blocked_tool_result(tool_call, (
                f"TOOL_SCHEMA_ERROR: `{tool_call.name}` "
                + json.dumps(issues, ensure_ascii=False)
                + "\nNo tool was executed. Correct only the reported fields using the advertised schema. "
                "Do not repeat unchanged arguments. Edit.new_text may be empty for deletion."
            ))
        return None

    def _change_diff(self, path: str, before: str, after: str) -> str:
        return "\n".join(difflib.unified_diff(
            before.splitlines(),
            after.splitlines(),
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
            lineterm="",
        ))

    def _pending_change_payload(self, change: PendingChange) -> dict[str, Any]:
        return {
            "id": change.id,
            "sessionId": change.session_id,
            "action": change.action,
            "path": change.path,
            "diff": change.diff,
            "status": change.status,
            "beforeLength": len(change.before),
            "afterLength": len(change.after),
            "impact": change.impact,
        }

    async def _stage_file_change(
        self,
        session: AgentSession,
        tool_call: ToolCall,
        on_event: Optional[Callable[[AgentEvent], Any]],
    ) -> Optional[ToolResult]:
        if session.tool_policy != "research_artifacts" or tool_call.name not in {"Write", "Edit"}:
            return None

        path_value = tool_call.arguments.get("path")
        if not isinstance(path_value, str) or not path_value.strip():
            return self._blocked_tool_result(tool_call, "BLOCKED: missing path for file change proposal.")

        path = Path(path_value).expanduser().resolve()
        before = path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""

        if tool_call.name == "Write":
            after = str(tool_call.arguments.get("content", ""))
            action = "write" if path.exists() else "create"
        else:
            old_text = str(tool_call.arguments.get("old_text", ""))
            new_text = str(tool_call.arguments.get("new_text", ""))
            if not path.exists():
                return self._blocked_tool_result(tool_call, f"BLOCKED: cannot edit missing file: {path}")
            if old_text not in before:
                return self._blocked_tool_result(tool_call, "BLOCKED: old_text not found; no change proposal was created.")
            if before.count(old_text) != 1:
                return self._blocked_tool_result(tool_call, "BLOCKED: old_text is ambiguous; include more context.")
            after = before.replace(old_text, new_text, 1)
            action = "edit"

        if before == after:
            return ToolResult(
                tool_call_id=tool_call.id,
                success=True,
                output=f"No file change needed for {path}; proposed content is identical.",
            )

        change = PendingChange(
            id=uuid.uuid4().hex[:12],
            session_id=session.id,
            action=action,
            path=str(path),
            before=before,
            after=after,
            diff=self._change_diff(str(path), before, after),
        )
        session.pending_changes[change.id] = change
        from .session_persistence import persist_session_transcript

        if persist_session_transcript(session) is None:
            session.pending_changes.pop(change.id, None)
            raise OSError("Unable to persist the change proposal; no file was modified")
        await self._emit(on_event, AgentEvent(type="change_proposal", data=self._pending_change_payload(change)))
        return ToolResult(
            tool_call_id=tool_call.id,
            success=True,
            output=(
                f"CHANGE_PROPOSED {change.id}: {action} {path}. "
                "The file was not modified. The user must approve or reject this proposal in Chat."
            ),
        )

    async def resolve_pending_change(self, session_id: str, change_id: str, approved: bool) -> dict[str, Any]:
        session = self._sessions.get(session_id)
        if session and change_id not in session.pending_changes:
            # Frontend state can move to a fresh active session while an older proposal
            # remains visible. Fall back to a unique in-memory proposal match before
            # reporting it missing.
            matches = [
                candidate
                for candidate in self._sessions.values()
                if change_id in candidate.pending_changes
            ]
            if len(matches) == 1:
                session = matches[0]
        if not session:
            raise ValueError(f"Session {session_id} not found")
        change = session.pending_changes.get(change_id)
        if not change:
            raise ValueError(f"Change proposal {change_id} not found")
        if change.status != "pending":
            return self._pending_change_payload(change)

        if approved:
            target = Path(change.path).expanduser().resolve()
            project_root = self._project_root(session)
            if (not target.is_relative_to(project_root)
                    or not self._is_research_artifact_path(project_root, target)):
                change.status = "blocked"
                raise PermissionError(f"Change target is outside research artifacts: {change.path}")
            violation = self._write_policy_block(session, ToolCall(
                id=change.id, name="Write", arguments={"path": str(target), "content": change.after},
            ))
            if violation:
                raise ValueError(violation.error or violation.output)
            from ..services.research_change_application import apply_research_change

            change.impact = apply_research_change(project_root, change)
            change.status = "applied"
        else:
            change.status = "rejected"
        from .session_persistence import persist_session_transcript

        if persist_session_transcript(session) is None:
            raise OSError("Unable to persist change resolution; reconnect to recover its durable receipt")
        return self._pending_change_payload(change)

    def _normalize_artifact_argument(
        self, session: AgentSession, tool_call: ToolCall, key: str,
    ) -> Optional[ToolResult]:
        raw_value = tool_call.arguments.get(key)
        if tool_call.name in {"Glob", "Grep"} and key == "directory" and isinstance(raw_value, str) and not raw_value.strip():
            raw_value = "."
        if not isinstance(raw_value, str) or not raw_value.strip():
            return None
        raw_path = raw_value.strip()
        project_root = self._project_root(session)
        target = Path(raw_path).expanduser()
        target = (target if target.is_absolute() else project_root / target).resolve()
        blocked = self._blocked_search_pattern(session, tool_call, raw_path)
        if blocked:
            return blocked
        if session.tool_policy == "workflow_artifacts":
            return self._normalize_workflow_path(
                session, tool_call, key, raw_path, project_root, target
            )
        return self._normalize_chat_path(
            session, tool_call, key, raw_path, project_root, target
        )

    def _blocked_search_pattern(
        self, session: AgentSession, tool_call: ToolCall, raw_path: str,
    ) -> Optional[ToolResult]:
        if tool_call.name not in {"Glob", "Grep"}:
            return None
        pattern = str(tool_call.arguments.get("pattern") or "").strip()
        normalized = pattern.replace("\\", "/")
        if not pattern or (
            not Path(pattern).is_absolute()
            and not any(part == ".." for part in normalized.split("/"))
        ):
            return None
        surface = "科研工作流" if session.tool_policy == "workflow_artifacts" else "Chat 面板"
        return self._blocked_tool_result(
            tool_call,
            f"BLOCKED: {surface}不允许通过 Glob/Grep pattern 越出当前项目。请求 pattern: {pattern}",
        )

    def _normalize_workflow_path(
        self, session: AgentSession, tool_call: ToolCall, key: str,
        raw_path: str, project_root: Path, target: Path,
    ) -> Optional[ToolResult]:
        inside_project = target == project_root or self._is_inside(target, project_root)
        if tool_call.name == "Read" and not inside_project:
            target = self._recover_shared_reference_path(session, target)
        readonly_match = bool(
            tool_call.name == "Read"
            and any(
                target == readonly_root or self._is_inside(target, readonly_root)
                for raw_root in session.readonly_roots
                if (readonly_root := Path(raw_root).expanduser().resolve())
            )
        )
        if not inside_project and not readonly_match:
            return self._blocked_tool_result(
                tool_call,
                "BLOCKED: 科研工作流工具只能访问当前科研项目目录，"
                "或当前已加载 skill 的只读共享规范。"
                f"禁止访问其他项目外路径。请求路径: {raw_path}",
            )
        if tool_call.name in {"Write", "Edit", "WritePart", "AssembleDocument"}:
            from ..services.artifact_contract import artifact_write_error

            path_error = artifact_write_error(project_root, target)
            if path_error:
                return self._blocked_tool_result(tool_call, path_error)
        tool_call.arguments[key] = str(target)
        return None

    def _recover_shared_reference_path(
        self, session: AgentSession, target: Path,
    ) -> Path:
        lowered = [part.casefold() for part in target.parts]
        try:
            shared_index = lowered.index("shared-references")
        except ValueError:
            return target
        suffix = target.parts[shared_index + 1:]
        for raw_root in session.readonly_roots:
            root = Path(raw_root).expanduser().resolve()
            if root.name.casefold() != "shared-references":
                continue
            candidate = root.joinpath(*suffix).resolve()
            if candidate.is_file() and self._is_inside(candidate, root):
                return candidate
        return target

    def _normalize_chat_path(
        self, session: AgentSession, tool_call: ToolCall, key: str,
        raw_path: str, project_root: Path, target: Path,
    ) -> Optional[ToolResult]:
        if tool_call.name in {"Glob", "Grep"} and target == project_root:
            return self._blocked_tool_result(
                tool_call,
                f"BLOCKED: Chat 面板不会扫描整个项目根目录。只能访问研究产物目录：{RESEARCH_ARTIFACTS_LABEL}。",
            )
        if tool_call.name == "Bash" and key == "cwd" and target == project_root:
            tool_call.arguments[key] = str(target)
            return None
        if not self._is_research_artifact_path(project_root, target):
            return self._blocked_tool_result(
                tool_call,
                f"BLOCKED: Chat 面板只能访问研究产物目录：{RESEARCH_ARTIFACTS_LABEL}。禁止读取或修改 IDE 源码路径。请求路径: {raw_path}",
            )
        tool_call.arguments[key] = str(target)
        return None
    def _apply_tool_policy(
        self, session: AgentSession, tool_call: ToolCall,
    ) -> Optional[ToolResult]:
        from .write_scope import scoped_write_error

        scope_error = scoped_write_error(
            self._project_root(session), getattr(session, "allowed_write_paths", None),
            tool_call.name, tool_call.arguments,
        )
        if scope_error:
            return self._blocked_tool_result(tool_call, scope_error)
        write_block = self._write_policy_block(session, tool_call)
        if write_block:
            return write_block
        if session.tool_policy not in {"research_artifacts", "workflow_artifacts"}:
            return None
        if session.tool_policy == "research_artifacts" and tool_call.name == "Bash":
            return self._blocked_tool_result(
                tool_call,
                "BLOCKED: Chat 面板禁用 Bash，避免命令行修改 IDE 源码。请使用研究产物专用工具。",
            )
        if (
            session.tool_policy == "research_artifacts"
            and tool_call.name == "generate_figure"
            and str(tool_call.arguments.get("code", "")).strip()
        ):
            return self._blocked_tool_result(
                tool_call,
                "BLOCKED: Chat 面板禁止执行任意图表代码。请用描述式图表生成，或把可编辑源文件写入 figures/ 后由用户确认执行。",
            )
        if tool_call.name == "generate_figure" and not tool_call.arguments.get("output_dir"):
            tool_call.arguments["output_dir"] = str(self._project_root(session) / "figures")
        for key in self._tool_path_keys(tool_call.name):
            blocked = self._normalize_artifact_argument(session, tool_call, key)
            if blocked:
                return blocked
        if tool_call.name == "generate_figure":
            return self._normalize_artifact_argument(session, tool_call, "output_dir")
        return None

    def _write_policy_block(
        self, session: AgentSession, tool_call: ToolCall,
    ) -> Optional[ToolResult]:
        if tool_call.name not in {"Write", "Edit", "WritePart", "AssembleDocument"}:
            return None
        raw_path = tool_call.arguments.get(
            "path",
            tool_call.arguments.get("target_path"),
        )
        if not isinstance(raw_path, str) or not raw_path.strip():
            return None
        project_root = self._project_root(session)
        target = Path(raw_path).expanduser()
        target = (target if target.is_absolute() else project_root / target).resolve()
        if session.tool_policy == "workflow_artifacts":
            blocked = self._workflow_write_block(session, tool_call, project_root, target)
            if blocked:
                return blocked
        if self._runtime_owned_target(project_root, target):
            return self._blocked_tool_result(
                tool_call,
                "BLOCKED: this provenance file is runtime-owned and cannot be authored by a model.",
            )
        if self._is_inside(target, (project_root / ".merak" / "reference_context").resolve()):
            return self._blocked_tool_result(
                tool_call,
                "BLOCKED: reference_context is an immutable runtime-owned research snapshot.",
            )
        content = self._prospective_write_content(tool_call, target)
        if content is not None:
            from ..contracts.writers import versioned_artifact_write_error

            contract_error = versioned_artifact_write_error(
                project_root, target, content, model_authored=True,
            )
            if contract_error:
                return self._blocked_tool_result(tool_call, contract_error)
        return None

    @staticmethod
    def _prospective_write_content(
        tool_call: ToolCall, target: Path,
    ) -> str | None:
        if tool_call.name in {"WritePart", "AssembleDocument"}:
            return None
        if tool_call.name == "Write":
            return str(tool_call.arguments.get("content") or "")
        if not target.is_file():
            return None
        try:
            before = target.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeError):
            return None
        old = str(tool_call.arguments.get("old_text") or "")
        if not old or old not in before:
            return None
        return before.replace(old, str(tool_call.arguments.get("new_text") or ""), 1)

    def _workflow_write_block(
        self, session: AgentSession, tool_call: ToolCall,
        project_root: Path, target: Path,
    ) -> Optional[ToolResult]:
        node_id = str(session.workflow_node_id or "").strip()
        if not node_id:
            return None
        from ..services.project_scaffold import WORKFLOW_PATHS

        for relative in list((WORKFLOW_PATHS.get(node_id) or {}).get("write") or []):
            relative_text = str(relative).replace("\\", "/")
            boundary = (project_root / relative_text).resolve()
            allowed = (
                target == boundary or self._is_inside(target, boundary)
                if relative_text.endswith("/") else target == boundary
            )
            if allowed:
                return None
        return self._blocked_tool_result(
            tool_call,
            f"BLOCKED: workflow node {node_id} cannot write outside its owned artifacts. Requested path: {target}",
        )

    def _runtime_owned_target(self, project_root: Path, target: Path) -> bool:
        files = {
            (project_root / 'experiments/results/accepted_matrix.json').resolve(),
            (project_root / "literature" / "SEARCH_EVIDENCE.json").resolve(),
            (project_root / ".merak" / "research_strategy.json").resolve(),
            (project_root / ".merak" / "NARRATIVE_BUILD.json").resolve(),
            (project_root / "merak" / "NARRATIVE_BUILD.json").resolve(),
        }
        roots = (
            (project_root / '.merak/accepted-matrices').resolve(),
            (project_root / ".merak" / "runs").resolve(),
            (project_root / ".merak" / "quality").resolve(),
            (project_root / ".merak" / "meta").resolve(),
        )
        return target in files or any(self._is_inside(target, root) for root in roots)

    @staticmethod
    def _tool_path_keys(tool_name: str) -> list[str]:
        return {
            "Read": ["path"], "Write": ["path"], "Edit": ["path"],
            "WritePart": ["target_path"], "AssembleDocument": ["target_path"],
            "Glob": ["directory"], "Grep": ["directory"],
            "latex_compile": ["project_dir"], "scaffold_paper": ["project_dir"],
            "reviewer_api": ["file_path"], "evidence_check": ["source_path"],
            "provenance_stamp": ["artifact_path"],
            "extract_paper_style": ["source_path"], "Bash": ["cwd"],
        }.get(tool_name, [])
