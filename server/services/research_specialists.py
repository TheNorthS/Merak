"""Profile-aware specialist subnodes for the research workflow.

The thirteen public workflow nodes stay stable. This service adds bounded,
artifact-owning model subnodes only when the inferred study profile requires
them. A subnode counts as executed only after its complete SKILL.md was loaded
by invoke_skill and its canonical artifact passes a local contract.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

from ..utils.atomic_write import atomic_write_json
from .specialist_catalog import SpecialistSpec, selected_specialists
from .specialist_inputs import (
    input_relatives,
    scientific_input_bytes,
    specialist_input_digest,
)
from .specialist_plan import prepare_specialist_plan
from .specialist_execution import execute_specialists_for_node


SPECIALIST_PLAN_SCHEMA = 1
SPECIALIST_ARTIFACT_MIN_BYTES = 240


EmitFn = Callable[[str, dict[str, Any]], Awaitable[None]]


class ResearchSpecialistService:
    relative_suffix = ".specialists.json"

    @staticmethod
    def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
        atomic_write_json(path, payload)

    @staticmethod
    def _sha256(path: Path) -> str:
        try:
            return hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError:
            return ""

    @staticmethod
    def _is_transient_failure(error: object) -> bool:
        text = str(error or "").casefold()
        markers = (
            "429",
            "502",
            "503",
            "504",
            "bad gateway",
            "service temporarily unavailable",
            "service unavailable",
            "temporarily unavailable",
            "rate limit",
            "overloaded",
            "timeout",
            "timed out",
            "请求超时",
            "connection reset",
            "connection aborted",
            "peer closed connection",
            "incomplete chunked read",
        )
        return any(marker in text for marker in markers)

    @classmethod
    def plan_path(cls, project_path: str | Path, run_id: str) -> Path:
        root = Path(project_path).expanduser().resolve()
        return root / ".merak" / "runs" / f"{run_id}{cls.relative_suffix}"

    @classmethod
    def load(cls, project_path: str | Path, run_id: str) -> dict[str, Any]:
        path = cls.plan_path(project_path, run_id)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return payload if isinstance(payload, dict) else {}

    @staticmethod
    def _selected_specs(family: str, archetype: str) -> list[SpecialistSpec]:
        return selected_specialists(family, archetype)
    @classmethod
    def _artifact_valid(
        cls,
        root: Path,
        entry: dict[str, Any],
    ) -> tuple[bool, list[str]]:
        relative = str(entry.get("artifact") or "")
        path = (root / relative).resolve()
        issues: list[str] = []
        try:
            path.relative_to(root)
        except ValueError:
            return False, [f"specialist artifact escapes project: {relative}"]
        if not path.is_file() or path.stat().st_size < SPECIALIST_ARTIFACT_MIN_BYTES:
            return False, [f"missing or thin specialist artifact: {relative}"]
        text = path.read_text(encoding="utf-8", errors="replace").casefold()
        for heading in entry.get("required_headings") or []:
            if str(heading).casefold() not in text:
                issues.append(f"{relative} missing required marker: {heading}")
        return not issues, issues

    @classmethod
    def _invocation_trace_valid(
        cls,
        root: Path,
        entry: dict[str, Any],
    ) -> tuple[bool, str]:
        raw_path = str(entry.get("invocation_trace") or "").strip()
        if not raw_path:
            return False, "missing specialist skill invocation trace"
        path = Path(raw_path).expanduser().resolve()
        trace_root = (root / ".merak" / "skill-invocations").resolve()
        try:
            path.relative_to(trace_root)
        except ValueError:
            return False, "specialist invocation trace is outside the project"
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False, "specialist invocation trace is missing or invalid"
        expected_session = str(entry.get("session_id") or "").strip()
        expected_skill = str(entry.get("skill") or "").lstrip("/")
        valid = bool(
            payload.get("status") == "completed"
            and payload.get("policy_loaded") is True
            and expected_session
            and str(payload.get("session_id") or "") == expected_session
            and str(payload.get("skill") or "").lstrip("/") == expected_skill
            and str(payload.get("skill_sha256") or "").strip()
            and int(payload.get("skill_bytes") or 0) > 0
        )
        return (True, "") if valid else (
            False, "specialist invocation trace lacks full-skill model evidence"
        )

    @staticmethod
    def _input_digest(
        root: Path,
        style: dict[str, Any],
        spec: SpecialistSpec,
        options: dict[str, Any],
    ) -> str:
        return specialist_input_digest(root, style, spec, options)

    @staticmethod
    def _scientific_input_bytes(path: Path) -> bytes:
        return scientific_input_bytes(path)

    @staticmethod
    def _input_relatives(node_id: str) -> tuple[str, ...]:
        return input_relatives(node_id)
    @classmethod
    def _reusable_entry(
        cls,
        root: Path,
        current_path: Path,
        entry: dict[str, Any],
    ) -> Optional[dict[str, Any]]:
        runs_dir = current_path.parent
        if not runs_dir.is_dir():
            return None
        candidates = sorted(
            (path for path in runs_dir.glob(f"*{cls.relative_suffix}") if path != current_path),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        for path in candidates[:20]:
            try:
                previous = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            for candidate in previous.get("subnodes", []):
                if not isinstance(candidate, dict):
                    continue
                if candidate.get("id") != entry.get("id"):
                    continue
                if candidate.get("input_digest") != entry.get("input_digest"):
                    continue
                valid, _ = cls._artifact_valid(root, candidate)
                artifact = root / str(candidate.get("artifact") or "")
                trace_valid, _ = cls._invocation_trace_valid(root, candidate)
                if (
                    valid
                    and candidate.get("status") == "completed"
                    and trace_valid
                    and candidate.get("artifact_sha256")
                    and candidate.get("artifact_sha256") == cls._sha256(artifact)
                ):
                    return candidate
        return None

    @classmethod
    def _recover_project_trace_entry(
        cls,
        root: Path,
        entry: dict[str, Any],
    ) -> Optional[dict[str, Any]]:
        """Rebuild a lost plan row from a completed local skill trace."""
        valid, _ = cls._artifact_valid(root, entry)
        if not valid:
            return None
        input_mtimes = [
            (root / relative).stat().st_mtime
            for relative in cls._input_relatives(str(entry.get("node_id") or ""))
            if (root / relative).is_file()
        ]
        latest_input_mtime = max(input_mtimes, default=0.0)
        trace_root = root / ".merak" / "skill-invocations"
        skill_name = str(entry.get("skill") or "").lstrip("/")
        candidates: list[tuple[float, Path, dict[str, Any]]] = []
        if trace_root.is_dir():
            for path in trace_root.glob(f"*_{skill_name}.json"):
                try:
                    payload = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue
                finished_at = float(payload.get("finished_at") or 0)
                if (
                    payload.get("status") == "completed"
                    and payload.get("policy_loaded") is True
                    and str(payload.get("session_id") or "").strip()
                    and str(payload.get("skill") or "").lstrip("/") == skill_name
                    and str(payload.get("skill_sha256") or "").strip()
                    and int(payload.get("skill_bytes") or 0) > 0
                    and finished_at >= latest_input_mtime
                ):
                    candidates.append((finished_at, path, payload))
        if not candidates:
            return None
        finished_at, trace_path, trace = max(candidates, key=lambda item: item[0])
        recovered = {
            **entry,
            "status": "completed",
            "artifact_sha256": cls._sha256(root / str(entry["artifact"])),
            "session_id": str(trace.get("session_id") or ""),
            "completed_at": finished_at,
            "invocation_trace": str(trace_path),
            "recovered_from_project_trace": True,
        }
        return recovered if cls._invocation_trace_valid(root, recovered)[0] else None

    @classmethod
    def _completed_trace_fallback_entry(
        cls,
        root: Path,
        entry: dict[str, Any],
    ) -> Optional[dict[str, Any]]:
        """Recover the last valid local result after a transport-only failure.

        A failed retry must not destroy an earlier successful specialist result.
        The artifact must still be valid, unchanged since that completed trace,
        and trace-backed.  This is intentionally used only for transient model
        transport failures; scientific or contract failures still require a
        fresh execution.
        """
        valid, _ = cls._artifact_valid(root, entry)
        artifact = root / str(entry.get("artifact") or "")
        if not valid or not artifact.is_file():
            return None
        trace_root = root / ".merak" / "skill-invocations"
        skill_name = str(entry.get("skill") or "").lstrip("/")
        candidates: list[tuple[float, Path, dict[str, Any]]] = []
        if trace_root.is_dir():
            for path in trace_root.glob(f"*_{skill_name}.json"):
                try:
                    trace = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue
                finished_at = float(trace.get("finished_at") or 0)
                if (
                    trace.get("status") == "completed"
                    and trace.get("policy_loaded") is True
                    and str(trace.get("session_id") or "").strip()
                    and str(trace.get("skill") or "").lstrip("/") == skill_name
                    and str(trace.get("skill_sha256") or "").strip()
                    and int(trace.get("skill_bytes") or 0) > 0
                    # The current bytes must be the artifact that already
                    # existed when the successful invocation completed.
                    and artifact.stat().st_mtime <= finished_at + 1.0
                ):
                    candidates.append((finished_at, path, trace))
        if not candidates:
            return None
        finished_at, trace_path, trace = max(candidates, key=lambda item: item[0])
        recovered = {
            **entry,
            "status": "completed",
            "artifact_sha256": cls._sha256(artifact),
            "session_id": str(trace.get("session_id") or ""),
            "completed_at": finished_at,
            "model_provider": str(trace.get("model_provider") or ""),
            "model_name": str(trace.get("model_name") or ""),
            "invocation_trace": str(trace_path),
            "reused_after_transport_failure": True,
        }
        return recovered if cls._invocation_trace_valid(root, recovered)[0] else None

    def prepare(
        self,
        project_path: str | Path,
        run_id: str,
        direction: str,
        options: dict[str, Any],
        selected_node_ids: list[str] | set[str] | tuple[str, ...],
    ) -> dict[str, Any]:
        return prepare_specialist_plan(
            self, project_path, run_id, direction, options, selected_node_ids
        )

    async def execute_for_node(
        self,
        project_path: str | Path,
        run_id: str,
        node_id: str,
        direction: str,
        options: dict[str, Any],
        selected_node_ids: list[str] | set[str] | tuple[str, ...],
        *,
        emit: Optional[EmitFn] = None,
    ) -> list[dict[str, Any]]:
        return await execute_specialists_for_node(
            self, project_path, run_id, node_id, direction, options,
            selected_node_ids, emit,
        )
    @staticmethod
    def _latest_invocation_trace(
        root: Path,
        skill_name: str,
        started_at: float,
    ) -> dict[str, Any]:
        trace_root = root / ".merak" / "skill-invocations"
        matches: list[tuple[float, Path, dict[str, Any]]] = []
        if trace_root.is_dir():
            for path in trace_root.glob(f"*_{skill_name}.json"):
                try:
                    payload = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue
                timestamp = float(payload.get("started_at") or 0)
                if timestamp >= started_at - 1:
                    matches.append((timestamp, path, payload))
        if not matches:
            return {}
        _, path, payload = max(matches, key=lambda item: item[0])
        return {**payload, "trace_path": str(path)}

    def gate_node(
        self,
        project_path: str | Path,
        run_id: str,
        node_id: str,
    ) -> dict[str, Any]:
        root = Path(project_path).expanduser().resolve()
        payload = self.load(root, run_id)
        entries = [
            item for item in payload.get("subnodes", [])
            if isinstance(item, dict) and item.get("node_id") == node_id
        ]
        if not entries:
            return {
                "accepted": True,
                "applicable": False,
                "issues": [],
                "subnodes": [],
            }
        issues: list[str] = []
        for entry in entries:
            if entry.get("dependency_review"):
                from .specialist_dependency_review import dependency_review_valid
                if not dependency_review_valid(root, entry["dependency_review"], entry["input_digest"], root / entry["artifact"]):
                    issues.append(f"specialist dependency review is stale: {entry['id']}")
            if entry.get("status") not in {"completed", "reused"}:
                issues.append(
                    f"specialist subnode {entry.get('id')} is {entry.get('status', 'pending')}"
                )
            valid, artifact_issues = self._artifact_valid(root, entry)
            if not valid:
                issues.extend(artifact_issues)
            if entry.get("status") == "completed":
                trace_valid, trace_issue = self._invocation_trace_valid(root, entry)
                if not trace_valid:
                    issues.append(f"{entry.get('id')}: {trace_issue}")
            elif entry.get("status") == "reused" and not str(
                entry.get("reused_from_run") or ""
            ).strip():
                issues.append(
                    f"{entry.get('id')}: reused specialist lacks source run provenance"
                )
            artifact = root / str(entry.get("artifact") or "")
            if entry.get("artifact_sha256") and entry.get("artifact_sha256") != self._sha256(artifact):
                issues.append(f"specialist artifact changed after execution: {entry.get('artifact')}")
        return {
            "accepted": not issues,
            "applicable": True,
            "issues": issues,
            "plan_path": str(self.plan_path(root, run_id)),
            "profile": payload.get("profile", {}),
            "subnodes": entries,
        }


research_specialist_service = ResearchSpecialistService()
