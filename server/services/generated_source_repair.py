"""Conservative, auditable repairs for malformed agent-generated source files."""

from __future__ import annotations

import ast
import hashlib
import json
import re
import time
from pathlib import Path
from typing import Any

from ..utils.atomic_write import atomic_write_json, atomic_write_text, path_lock


class GeneratedSourceRepairService:
    """Repair only syntax failures with a uniquely verifiable local rewrite."""

    report_relative_path = Path(".merak") / "repairs" / "SOURCE_REPAIRS.json"

    @staticmethod
    def _sha256(content: str) -> str:
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    @staticmethod
    def _parses(content: str, path: Path) -> bool:
        try:
            ast.parse(content, filename=str(path))
        except SyntaxError:
            return False
        return True

    @staticmethod
    def _duplicate_module_docstring_repair(content: str, path: Path) -> tuple[str, str]:
        """Remove one adjacent duplicate module-docstring opener if parsing proves it."""
        lines = content.splitlines(keepends=True)
        index = 0
        if index < len(lines) and lines[index].startswith("#!"):
            index += 1
        if index < len(lines) and re.match(r"^#.*coding[:=]", lines[index]):
            index += 1
        while index < len(lines) and not lines[index].strip():
            index += 1
        if index + 1 >= len(lines):
            return content, ""

        first = lines[index].lstrip()
        second = lines[index + 1].lstrip()
        quote = next((item for item in ('"""', "'''") if first.startswith(item)), "")
        if not quote or not second.startswith(quote):
            return content, ""
        if quote in first[len(quote):] or quote in second[len(quote):]:
            return content, ""

        for remove_index, repair_kind in (
            (index + 1, "duplicate_module_docstring_opener"),
            (index, "superseded_module_docstring_opener"),
        ):
            candidate = "".join(lines[:remove_index] + lines[remove_index + 1:])
            if GeneratedSourceRepairService._parses(candidate, path):
                return candidate, repair_kind
        return content, ""

    @staticmethod
    def _record_repairs(report_path: Path, repaired: list[dict[str, Any]]) -> None:
        with path_lock(report_path):
            try:
                payload = json.loads(report_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                payload = {"schema": 1, "repairs": []}
            history = payload.get("repairs") if isinstance(payload.get("repairs"), list) else []
            history.extend(repaired)
            payload.update({
                "schema": 1,
                "updated_at": time.time(),
                "repairs": history[-200:],
            })
            atomic_write_json(report_path, payload)

    def repair_python_sources(
        self,
        project_path: str | Path,
        *,
        node_id: str = "exp-design",
    ) -> dict[str, Any]:
        root = Path(project_path).expanduser().resolve()
        source_root = root / "experiments" / "src"
        repaired: list[dict[str, Any]] = []
        unresolved: list[dict[str, str]] = []
        if not source_root.is_dir():
            return {"repaired": repaired, "unresolved": unresolved, "report_path": ""}

        for path in sorted(source_root.rglob("*.py")):
            if "__pycache__" in path.parts or not path.is_file():
                continue
            try:
                original = path.read_text(encoding="utf-8-sig", errors="strict")
                ast.parse(original, filename=str(path))
                continue
            except (OSError, UnicodeError) as exc:
                unresolved.append({"path": path.relative_to(root).as_posix(), "error": str(exc)})
                continue
            except SyntaxError as exc:
                error_before = f"{exc.msg} (line {exc.lineno or '?'})"

            candidate, repair_kind = self._duplicate_module_docstring_repair(original, path)
            if not repair_kind:
                unresolved.append({
                    "path": path.relative_to(root).as_posix(),
                    "error": error_before,
                })
                continue

            before_hash = self._sha256(original)
            after_hash = self._sha256(candidate)
            relative = path.relative_to(root)
            backup = root / ".merak" / "repairs" / "backups" / before_hash[:16] / relative
            with path_lock(path):
                try:
                    latest = path.read_text(encoding="utf-8")
                except (OSError, UnicodeError) as exc:
                    unresolved.append({
                        "path": relative.as_posix(),
                        "error": str(exc),
                    })
                    continue
                if latest != original:
                    unresolved.append({
                        "path": relative.as_posix(),
                        "error": "source changed while deterministic repair was prepared",
                    })
                    continue
                atomic_write_text(backup, original)
                atomic_write_text(path, candidate)
            repaired.append({
                "node_id": node_id,
                "path": relative.as_posix(),
                "kind": repair_kind,
                "error_before": error_before,
                "before_sha256": before_hash,
                "after_sha256": after_hash,
                "backup_path": backup.relative_to(root).as_posix(),
                "repaired_at": time.time(),
            })

        report_path = root / self.report_relative_path
        if repaired:
            self._record_repairs(report_path, repaired)

        return {
            "repaired": repaired,
            "unresolved": unresolved,
            "report_path": str(report_path) if repaired else "",
        }


generated_source_repair_service = GeneratedSourceRepairService()
