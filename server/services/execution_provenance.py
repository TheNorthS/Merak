"""Runtime-owned provenance for experiment commands and their result files."""

from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path
from typing import Any

from ..utils.atomic_write import atomic_write_json


_EXECUTION_TOOLS = {"Bash", "ssh_exec", "ssh_deploy"}
_EVIDENCE_SUFFIXES = {".json", ".csv", ".tsv", ".npz"}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _redact_command(command: str) -> str:
    return re.sub(
        r"(?i)([A-Z0-9_]*(?:KEY|TOKEN|SECRET|PASSWORD)[A-Z0-9_]*\s*=\s*)([^\s;&|]+)",
        r"\1<redacted>",
        command,
    )[:8000]


class ExecutionProvenanceService:
    """Persist execution facts from the tool runtime, outside model-authored artifacts."""

    def path(self, project_path: str | Path) -> Path:
        return Path(project_path).expanduser().resolve() / ".merak" / "execution_events.jsonl"

    def import_dir(self, project_path: str | Path) -> Path:
        return (
            Path(project_path).expanduser().resolve()
            / ".merak"
            / "evidence-imports"
        )

    @staticmethod
    def _is_result_path(relative: Path) -> bool:
        parts = tuple(part.casefold() for part in relative.parts)
        return bool(
            len(parts) >= 3
            and parts[:2] in {
                ("experiments", "results"),
                ("experiments", "logs"),
            }
        )

    def record_import(
        self,
        project_path: str | Path,
        *,
        run_id: str,
        evidence_mode: str,
        input_baseline: dict[str, Any],
    ) -> dict[str, Any]:
        """Bind researcher-selected result files to an immutable import manifest."""
        root = Path(project_path).expanduser().resolve()
        mode = str(evidence_mode or "").strip().casefold()
        if mode not in {"existing_results", "secondary_analysis"}:
            raise ValueError(f"unsupported evidence import mode: {mode or 'missing'}")
        artifacts: dict[str, dict[str, Any]] = {}
        for entry in input_baseline.get("entries") or []:
            if not isinstance(entry, dict):
                continue
            raw = str(entry.get("path") or "").strip()
            if not raw:
                continue
            candidate = (root / raw).resolve()
            try:
                relative = candidate.relative_to(root)
            except ValueError:
                continue
            if not self._is_result_path(relative):
                continue
            paths = [candidate] if candidate.is_file() else (
                sorted(candidate.rglob("*")) if candidate.is_dir() else []
            )
            for path in paths:
                if (
                    not path.is_file()
                    or path.suffix.casefold() not in _EVIDENCE_SUFFIXES
                ):
                    continue
                child_relative = path.relative_to(root).as_posix()
                artifacts[child_relative] = {
                    "sha256": _sha256(path),
                    "bytes": path.stat().st_size,
                }
        manifest = {
            "schema": 1,
            "run_id": str(run_id),
            "evidence_mode": mode,
            "source": "researcher_selected_workflow_input",
            "input_snapshot_id": str(input_baseline.get("snapshot_id") or ""),
            "imported_at": time.time(),
            "artifacts": artifacts,
        }
        output_dir = self.import_dir(root)
        output_dir.mkdir(parents=True, exist_ok=True)
        output = output_dir / f"{run_id}.json"
        atomic_write_json(output, manifest)
        return {**manifest, "manifest_path": output.relative_to(root).as_posix()}

    def imported_sources(self, project_path: str | Path) -> set[str]:
        """Return current result files backed by a user-approved import hash."""
        root = Path(project_path).expanduser().resolve()
        import_dir = self.import_dir(root)
        if not import_dir.is_dir():
            return set()
        proven: set[str] = set()
        for manifest_path in sorted(import_dir.glob("*.json")):
            try:
                payload = json.loads(
                    manifest_path.read_text(encoding="utf-8-sig")
                )
            except (OSError, UnicodeError, json.JSONDecodeError):
                continue
            if (
                not isinstance(payload, dict)
                or str(payload.get("evidence_mode") or "").casefold()
                not in {"existing_results", "secondary_analysis"}
            ):
                continue
            for relative, facts in dict(payload.get("artifacts") or {}).items():
                path = (root / str(relative)).resolve()
                try:
                    normalized = path.relative_to(root)
                except ValueError:
                    continue
                if (
                    self._is_result_path(normalized)
                    and path.is_file()
                    and path.stat().st_size > 0
                    and str(facts.get("sha256") or "") == _sha256(path)
                ):
                    proven.add(normalized.as_posix())
        return proven

    def config_hashes(self, project_path: str | Path) -> dict[str, str]:
        root = Path(project_path).expanduser().resolve()
        config_root = root / "experiments" / "configs"
        if not config_root.exists():
            return {}
        result: dict[str, str] = {}
        for path in sorted(config_root.rglob("*")):
            if path.is_file() and path.suffix.lower() in {".yaml", ".yml", ".json", ".toml", ".ini", ".cfg"}:
                result[path.relative_to(root).as_posix()] = _sha256(path)
        return result

    def result_artifacts(self, project_path: str | Path) -> dict[str, dict[str, float | str]]:
        root = Path(project_path).expanduser().resolve()
        artifact_roots = [root / "experiments" / "results", root / "experiments" / "logs"]
        artifacts: dict[str, dict[str, float | str]] = {}
        for artifact_root in artifact_roots:
            if not artifact_root.exists():
                continue
            for path in sorted(artifact_root.rglob("*")):
                if not path.is_file() or path.suffix.lower() not in {
                    ".json", ".jsonl", ".csv", ".tsv", ".npz", ".npy",
                    ".parquet", ".feather", ".yaml", ".yml", ".log", ".txt",
                }:
                    continue
                artifacts[path.relative_to(root).as_posix()] = {
                    "sha256": _sha256(path),
                    "mtime": path.stat().st_mtime,
                    "bytes": path.stat().st_size,
                }
        return artifacts

    def record(
        self,
        project_path: str | Path,
        session_id: str,
        tool: str,
        arguments: dict[str, Any],
        success: bool,
        started_at: float,
        finished_at: float,
        output: str = "",
    ) -> None:
        if tool not in _EXECUTION_TOOLS:
            return
        root = Path(project_path).expanduser().resolve()
        command = str(arguments.get("command") or arguments.get("script_path") or "")
        payload = {
            "schema": 1,
            "event_id": hashlib.sha256(
                f"{session_id}:{tool}:{started_at}:{command}".encode("utf-8")
            ).hexdigest()[:16],
            "session_id": session_id,
            "tool": tool,
            "started_at": started_at,
            "finished_at": finished_at,
            "success": bool(success),
            "command": _redact_command(command),
            "cwd": str(arguments.get("cwd") or root),
            "server_id": str(arguments.get("server_id") or ""),
            "config_hashes": self.config_hashes(root),
            "result_artifacts": self.result_artifacts(root),
            "output_sha256": hashlib.sha256(str(output).encode("utf-8", errors="replace")).hexdigest(),
        }
        path = self.path(root)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")

    def load(self, project_path: str | Path) -> list[dict[str, Any]]:
        path = self.path(project_path)
        if not path.exists():
            return []
        events: list[dict[str, Any]] = []
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                events.append(payload)
        return events

    def managed_runs(self, project_path: str | Path) -> list[dict[str, Any]]:
        """Load successful scheduler-owned runs from every supported backend."""
        root = Path(project_path).expanduser().resolve()
        managed_root = root / ".merak" / "experiments"
        if not managed_root.is_dir():
            return []
        runs: list[dict[str, Any]] = []
        for path in sorted(managed_root.glob("*/run.json")):
            try:
                payload = json.loads(
                    path.read_text(encoding="utf-8-sig", errors="strict")
                )
            except (OSError, UnicodeError, json.JSONDecodeError):
                continue
            if (
                not isinstance(payload, dict)
                or payload.get("status") != "completed"
                or payload.get("evidence_eligible") is False
                or payload.get("submission_eligible") is False
                or not isinstance(payload.get("result_artifacts"), dict)
            ):
                continue
            runs.append({
                **payload,
                "manifest_path": path.relative_to(root).as_posix(),
            })
        return runs

    def proven_result_sources(
        self,
        project_path: str | Path,
        *,
        suffixes: set[str] | None = None,
    ) -> set[str]:
        """Return current files whose hashes are owned by a successful runtime."""
        root = Path(project_path).expanduser().resolve()
        allowed_suffixes = {
            str(value).casefold() for value in (suffixes or set()) if str(value)
        }

        def allowed(path: Path) -> bool:
            return not allowed_suffixes or path.suffix.casefold() in allowed_suffixes

        proven: set[str] = set()
        for event in self.load(root):
            if not event.get("success"):
                continue
            for relative, facts in dict(event.get("result_artifacts") or {}).items():
                path = root / str(relative)
                if (
                    path.is_file()
                    and allowed(path)
                    and path.stat().st_size > 0
                    and str(facts.get("sha256") or "") == _sha256(path)
                    and float(facts.get("mtime") or 0)
                    >= float(event.get("started_at") or 0) - 2.0
                ):
                    proven.add(path.relative_to(root).as_posix())
        for run in self.managed_runs(root):
            for relative, facts in dict(run.get("result_artifacts") or {}).items():
                path = root / str(relative)
                if (
                    path.is_file()
                    and allowed(path)
                    and path.stat().st_size > 0
                    and str(facts.get("sha256") or "") == _sha256(path)
                ):
                    proven.add(path.relative_to(root).as_posix())
        proven.update(
            relative for relative in self.imported_sources(root)
            if allowed(root / relative)
        )
        return proven

    def validate_reference_runs(
        self,
        project_path: str | Path,
        metric_paths: list[Path],
    ) -> list[str]:
        root = Path(project_path).expanduser().resolve()
        events = [event for event in self.load(root) if event.get("success")]
        if not events:
            return ["no successful runtime-owned experiment execution event was recorded"]
        current_hashes = self.config_hashes(root)
        required_configs = {
            "experiments/configs/reference_baseline.yaml": "reference_baseline",
            "experiments/configs/proposed_method.yaml": "proposed_method",
        }
        issues: list[str] = []
        matched_events: list[dict[str, Any]] = []
        for config_path, command_marker in required_configs.items():
            current_hash = current_hashes.get(config_path)
            candidates = [
                event for event in events
                if command_marker in str(event.get("command") or "")
                and current_hash
                and event.get("config_hashes", {}).get(config_path) == current_hash
            ]
            if not candidates:
                issues.append(
                    f"no successful execution event used the current {config_path}"
                )
            else:
                matched_events.extend(candidates)

        if matched_events:
            for path in metric_paths:
                if not path.exists():
                    continue
                rel = path.relative_to(root).as_posix()
                current_hash = _sha256(path)
                proven = any(
                    event.get("result_artifacts", {}).get(rel, {}).get("sha256") == current_hash
                    and float(event.get("result_artifacts", {}).get(rel, {}).get("mtime") or 0)
                    >= float(event.get("started_at") or 0) - 2.0
                    for event in matched_events
                )
                if not proven:
                    issues.append(
                        f"metric artifact hash/timestamp is not owned by a matched execution event: {rel}"
                    )
        return issues


execution_provenance_service = ExecutionProvenanceService()
