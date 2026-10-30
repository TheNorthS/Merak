"""Auditable intake for research based on a reference paper and codebase."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import time
from pathlib import Path
from typing import Any

from ..utils.atomic_write import atomic_write_json, atomic_write_text


RESEARCH_MODES = {"from_scratch", "paper_code_innovation"}

_CODE_EXTENSIONS = {
    ".py", ".pyi", ".ipynb", ".js", ".jsx", ".ts", ".tsx", ".java", ".kt",
    ".c", ".cc", ".cpp", ".cxx", ".h", ".hpp", ".cu", ".cuh", ".rs", ".go",
    ".m", ".mm", ".r", ".jl", ".sh", ".ps1", ".bat", ".toml", ".yaml", ".yml",
    ".json", ".ini", ".cfg", ".md", ".rst", ".txt", ".tex", ".bib",
}
_EXCLUDED_DIRS = {
    ".git", ".hg", ".svn", ".idea", ".vscode", ".merak", "node_modules", "dist",
    "build", "target", "__pycache__", ".pytest_cache", ".mypy_cache", ".venv", "venv",
    "checkpoints", "wandb", "runs", "logs",
}
_SECRET_NAMES = {
    ".env", ".env.local", ".env.production", "credentials.json", "secrets.json",
    "user_settings.json", "id_rsa", "id_ed25519",
}
_BRIEF_SECTIONS = {
    "reference_paper": ("reference paper claims", "参考论文主张"),
    "reference_code": ("reference code reality", "参考代码实况", "代码实际实现"),
    "paper_code_gap": ("paper-code gaps", "paper code gaps", "论文代码差异"),
    "novelty_delta": ("novelty delta", "创新增量", "创新差异"),
    "neighbors": ("nearest neighbors", "近邻工作", "最相关工作"),
    "proposed_method": ("proposed method", "拟议方法", "新方法"),
    "baseline": ("baseline reproduction", "基线复现"),
    "falsification": ("falsification", "ablation", "证伪", "消融"),
    "claim_evidence": ("claim-evidence", "claim to evidence", "主张证据"),
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_url(value: str) -> bool:
    return bool(re.match(r"^https?://", value.strip(), flags=re.IGNORECASE))


class ResearchIntakeService:
    """Snapshot reference inputs so every downstream claim sees the same evidence."""

    max_files = 800
    max_total_bytes = 16 * 1024 * 1024
    max_single_file_bytes = 2 * 1024 * 1024
    max_pdf_pages = 80
    max_paper_chars = 400_000

    def validate_inputs(self, mode: str, reference_paper: str, reference_code: str) -> list[str]:
        problems: list[str] = []
        if mode not in RESEARCH_MODES:
            return [f"Unsupported research mode: {mode}"]
        if mode != "paper_code_innovation":
            return problems
        if not reference_paper.strip():
            problems.append("Reference Paper (PDF/TeX) is required in paper + code innovation mode.")
        if not reference_code.strip():
            problems.append("Reference Code Directory is required in paper + code innovation mode.")
        if reference_paper.strip() and _is_url(reference_paper):
            problems.append("Reference paper URLs are not snapshotted; select a local PDF, TeX file, or TeX directory.")
        if reference_code.strip() and _is_url(reference_code):
            problems.append("Reference repository URLs are not cloned automatically; select a local checked-out code directory.")
        if reference_paper.strip() and not _is_url(reference_paper):
            path = Path(reference_paper).expanduser()
            if not path.exists():
                problems.append(f"Reference paper path does not exist: {path}")
            elif path.is_file() and path.suffix.lower() not in {".pdf", ".tex"}:
                problems.append("Reference paper must be a PDF, a TeX file, or a TeX project directory.")
            elif path.is_dir() and not any(path.rglob("*.tex")) and not any(path.rglob("*.pdf")):
                problems.append("Reference paper directory contains no PDF or TeX source.")
        if reference_code.strip() and not _is_url(reference_code):
            path = Path(reference_code).expanduser()
            if not path.exists() or not path.is_dir():
                problems.append(f"Reference code directory does not exist: {path}")
        return problems

    def prepare(
        self,
        project_path: str | Path,
        reference_paper: str,
        reference_code: str,
        innovation_focus: str = "",
    ) -> dict[str, Any]:
        problems = self.validate_inputs("paper_code_innovation", reference_paper, reference_code)
        if problems:
            raise ValueError("; ".join(problems))

        root = Path(project_path).expanduser().resolve()
        paper_source = Path(reference_paper).expanduser().resolve()
        code_source = Path(reference_code).expanduser().resolve()
        context_root = root / ".merak" / "reference_context"
        context_root.mkdir(parents=True, exist_ok=True)

        paper_descriptor = self._describe_paper(paper_source)
        code_entries = self._collect_code_entries(code_source)
        digest = hashlib.sha256(
            json.dumps(
                {
                    "paper": paper_descriptor.get("fingerprint"),
                    "code": [(item["relative_path"], item["sha256"]) for item in code_entries],
                },
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()[:16]
        snapshot_root = context_root / "snapshots" / digest
        snapshot_root.mkdir(parents=True, exist_ok=True)

        paper_snapshot = self._snapshot_paper(paper_source, snapshot_root / "paper")
        code_snapshot = self._snapshot_code(code_source, code_entries, snapshot_root / "code")
        payload = {
            "schema": 1,
            "created_at": time.time(),
            "mode": "paper_code_innovation",
            "snapshot_id": digest,
            "innovation_focus": innovation_focus.strip(),
            "reference_paper": {
                "source_path": str(paper_source),
                **paper_descriptor,
                **paper_snapshot,
            },
            "reference_code": {
                "source_path": str(code_source),
                "snapshot_path": str(snapshot_root / "code"),
                "file_count": len(code_entries),
                "total_bytes": sum(int(item["bytes"]) for item in code_entries),
                "files": code_entries,
                **code_snapshot,
            },
            "required_outputs": {
                "innovation_brief": "ideas/INNOVATION_BRIEF.md",
                "experiment_plan": "experiments/EXPERIMENT_PLAN.md",
                "reference_baseline_metrics": "experiments/results/reference_baseline/metrics.json",
                "proposed_method_metrics": "experiments/results/proposed_method/metrics.json",
            },
        }
        context_path = context_root / "REFERENCE_CONTEXT.json"
        atomic_write_json(context_path, payload)
        self._write_intake_markdown(context_root / "REFERENCE_INTAKE.md", payload)
        return payload

    def _describe_paper(self, source: Path) -> dict[str, Any]:
        if source.is_file():
            return {
                "kind": source.suffix.lower().lstrip("."),
                "fingerprint": _sha256(source),
                "source_bytes": source.stat().st_size,
            }
        files = sorted(
            path for path in source.rglob("*")
            if path.is_file() and path.suffix.lower() in {".tex", ".bib", ".pdf"}
        )[:160]
        digest = hashlib.sha256()
        for path in files:
            digest.update(path.relative_to(source).as_posix().encode("utf-8"))
            digest.update(_sha256(path).encode("ascii"))
        return {
            "kind": "tex_project" if any(path.suffix.lower() == ".tex" for path in files) else "pdf_directory",
            "fingerprint": digest.hexdigest(),
            "source_bytes": sum(path.stat().st_size for path in files),
        }

    def _snapshot_paper(self, source: Path, destination: Path) -> dict[str, Any]:
        destination.mkdir(parents=True, exist_ok=True)
        text_parts: list[str] = []
        copied: list[str] = []
        pdf_source: Path | None = None
        if source.is_file():
            if source.suffix.lower() == ".pdf":
                pdf_source = source
                shutil.copy2(source, destination / "reference.pdf")
                copied.append("reference.pdf")
            else:
                shutil.copy2(source, destination / source.name)
                copied.append(source.name)
                text_parts.append(source.read_text(encoding="utf-8", errors="replace"))
        else:
            for path in sorted(source.rglob("*")):
                if not path.is_file() or path.suffix.lower() not in {".tex", ".bib"}:
                    continue
                rel = path.relative_to(source)
                target = destination / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, target)
                copied.append(rel.as_posix())
                if sum(len(part) for part in text_parts) < self.max_paper_chars:
                    text_parts.append(f"\n\n===== {rel.as_posix()} =====\n" + path.read_text(encoding="utf-8", errors="replace"))
            pdfs = sorted(source.rglob("*.pdf"))
            if pdfs:
                pdf_source = pdfs[0]
                shutil.copy2(pdf_source, destination / "reference.pdf")
                copied.append("reference.pdf")

        if pdf_source:
            extracted = self._extract_pdf(pdf_source)
            if extracted:
                text_parts.insert(0, extracted)
        text = "".join(text_parts)[: self.max_paper_chars]
        text_path = destination / "paper_text.txt"
        atomic_write_text(text_path, text)
        return {
            "snapshot_path": str(destination),
            "text_path": str(text_path),
            "text_characters": len(text),
            "copied_files": copied,
        }

    def _extract_pdf(self, path: Path) -> str:
        try:
            from pypdf import PdfReader

            reader = PdfReader(str(path))
            parts = []
            for page in reader.pages[: self.max_pdf_pages]:
                parts.append(page.extract_text() or "")
                if sum(len(part) for part in parts) >= self.max_paper_chars:
                    break
            return "\n\n".join(parts)[: self.max_paper_chars]
        except Exception:
            return ""

    def _collect_code_entries(self, root: Path) -> list[dict[str, Any]]:
        entries: list[dict[str, Any]] = []
        total = 0
        for path in sorted(root.rglob("*")):
            if len(entries) >= self.max_files or total >= self.max_total_bytes:
                break
            if not path.is_file():
                continue
            rel = path.relative_to(root)
            if any(part in _EXCLUDED_DIRS for part in rel.parts[:-1]):
                continue
            name_lower = path.name.lower()
            if name_lower in _SECRET_NAMES or name_lower.endswith((".pem", ".key", ".p12", ".pfx")):
                continue
            if path.suffix.lower() not in _CODE_EXTENSIONS and name_lower not in {"makefile", "dockerfile", "license"}:
                continue
            size = path.stat().st_size
            if size <= 0 or size > self.max_single_file_bytes or total + size > self.max_total_bytes:
                continue
            entries.append({
                "relative_path": rel.as_posix(),
                "bytes": size,
                "sha256": _sha256(path),
                "extension": path.suffix.lower() or name_lower,
            })
            total += size
        return entries

    def _snapshot_code(self, source: Path, entries: list[dict[str, Any]], destination: Path) -> dict[str, Any]:
        destination.mkdir(parents=True, exist_ok=True)
        for item in entries:
            rel = Path(item["relative_path"])
            target = destination / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source / rel, target)

        entrypoints = [
            item["relative_path"] for item in entries
            if Path(item["relative_path"]).name.lower() in {
                "train.py", "main.py", "run.py", "evaluate.py", "inference.py",
                "package.json", "pyproject.toml", "requirements.txt", "readme.md",
            }
        ]
        configs = [
            item["relative_path"] for item in entries
            if item["extension"] in {".yaml", ".yml", ".json", ".toml", ".ini", ".cfg"}
        ][:80]
        tests = [item["relative_path"] for item in entries if "test" in Path(item["relative_path"]).name.lower()][:80]
        index = {
            "entrypoints": entrypoints[:80],
            "configs": configs,
            "tests": tests,
            "extensions": self._extension_counts(entries),
        }
        atomic_write_json(destination / "CODE_INDEX.json", index)
        return index

    @staticmethod
    def _extension_counts(entries: list[dict[str, Any]]) -> dict[str, int]:
        counts: dict[str, int] = {}
        for item in entries:
            extension = str(item["extension"])
            counts[extension] = counts.get(extension, 0) + 1
        return dict(sorted(counts.items(), key=lambda pair: (-pair[1], pair[0])))

    @staticmethod
    def _write_intake_markdown(path: Path, payload: dict[str, Any]) -> None:
        paper = payload["reference_paper"]
        code = payload["reference_code"]
        focus = payload.get("innovation_focus") or "No additional focus supplied."
        lines = [
            "# Reference Research Intake",
            "",
            f"- Snapshot ID: `{payload['snapshot_id']}`",
            f"- Reference paper text: `{paper['text_path']}` ({paper['text_characters']} characters)",
            f"- Reference code snapshot: `{code['snapshot_path']}` ({code['file_count']} files)",
            f"- Innovation focus: {focus}",
            "",
            "## Entrypoints",
            *[f"- `{item}`" for item in code.get("entrypoints", [])],
            "",
            "## Required Analysis",
            "The workflow must compare paper claims with code reality, reproduce the reference baseline,",
            "define a falsifiable novelty delta, and test the proposed change with matched controls.",
        ]
        atomic_write_text(path, "\n".join(lines) + "\n")

    def validate_context(self, project_path: str | Path) -> tuple[bool, list[str], dict[str, Any]]:
        root = Path(project_path).expanduser().resolve()
        context_path = root / ".merak" / "reference_context" / "REFERENCE_CONTEXT.json"
        if not context_path.exists():
            return False, ["missing .merak/reference_context/REFERENCE_CONTEXT.json"], {}
        try:
            payload = json.loads(context_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False, ["reference context is not valid JSON"], {}
        issues: list[str] = []
        paper = payload.get("reference_paper", {})
        code = payload.get("reference_code", {})
        if int(paper.get("text_characters") or 0) < 500:
            issues.append("reference paper text extraction is too small for claim analysis")
        if int(code.get("file_count") or 0) < 1:
            issues.append("reference code snapshot contains no analyzable source files")
        for key in (paper.get("text_path"), code.get("snapshot_path")):
            if not key or not Path(key).exists():
                issues.append(f"missing reference snapshot artifact: {key}")
        return not issues, issues, payload

    def validate_innovation_brief(self, project_path: str | Path) -> tuple[bool, list[str]]:
        path = Path(project_path).expanduser().resolve() / "ideas" / "INNOVATION_BRIEF.md"
        if not path.exists() or path.stat().st_size == 0:
            return False, ["missing ideas/INNOVATION_BRIEF.md"]
        text = path.read_text(encoding="utf-8", errors="replace")
        lower = text.lower()
        issues: list[str] = []
        if len(text.strip()) < 1800:
            issues.append("innovation brief is too short (minimum 1800 characters)")
        context_path = Path(project_path).expanduser().resolve() / ".merak" / "reference_context" / "REFERENCE_CONTEXT.json"
        try:
            snapshot_id = str(json.loads(context_path.read_text(encoding="utf-8")).get("snapshot_id") or "")
        except (OSError, json.JSONDecodeError):
            snapshot_id = ""
        if snapshot_id and snapshot_id not in text:
            issues.append("innovation brief does not identify the active reference snapshot ID")
        for key, aliases in _BRIEF_SECTIONS.items():
            if not any(alias.lower() in lower for alias in aliases):
                issues.append(f"innovation brief missing section: {key}")
        return not issues, issues

    def validate_experiment_contract(
        self,
        project_path: str | Path,
        require_results: bool,
    ) -> tuple[bool, list[str]]:
        root = Path(project_path).expanduser().resolve()
        issues: list[str] = []
        plan = root / "experiments" / "EXPERIMENT_PLAN.md"
        plan_text = plan.read_text(encoding="utf-8", errors="replace") if plan.exists() else ""
        required_terms = {
            "reference baseline reproduction": ("reference baseline", "baseline reproduction", "基线复现"),
            "proposed method": ("proposed method", "our method", "新方法", "拟议方法"),
            "ablation/falsification": ("ablation", "falsification", "消融", "证伪"),
            "matched protocol": ("matched", "same split", "controlled", "相同数据划分", "受控"),
        }
        lower = plan_text.lower()
        for label, aliases in required_terms.items():
            if not any(alias.lower() in lower for alias in aliases):
                issues.append(f"experiment plan missing {label}")
        context_path = root / ".merak" / "reference_context" / "REFERENCE_CONTEXT.json"
        try:
            snapshot_id = str(json.loads(context_path.read_text(encoding="utf-8")).get("snapshot_id") or "")
        except (OSError, json.JSONDecodeError):
            snapshot_id = ""
        for rel in (
            "experiments/configs/reference_baseline.yaml",
            "experiments/configs/proposed_method.yaml",
        ):
            path = root / rel
            if not path.exists() or path.stat().st_size == 0:
                issues.append(f"missing {rel}")
            elif snapshot_id and snapshot_id not in path.read_text(encoding="utf-8", errors="replace"):
                issues.append(f"{rel} is not bound to reference snapshot {snapshot_id}")
        if require_results:
            metric_paths = [
                root / "experiments/results/reference_baseline/metrics.json",
                root / "experiments/results/proposed_method/metrics.json",
            ]
            for path in metric_paths:
                rel = path.relative_to(root).as_posix()
                if not path.exists() or path.stat().st_size == 0:
                    issues.append(f"missing executed result artifact {rel}")
                else:
                    try:
                        payload = json.loads(path.read_text(encoding="utf-8"))
                        if not isinstance(payload, dict) or not payload:
                            issues.append(f"empty metric payload {rel}")
                    except (OSError, json.JSONDecodeError):
                        issues.append(f"invalid metric JSON {rel}")
            from .execution_provenance import execution_provenance_service

            issues.extend(
                execution_provenance_service.validate_reference_runs(root, metric_paths)
            )
        return not issues, issues


research_intake_service = ResearchIntakeService()
