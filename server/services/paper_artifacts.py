"""Evidence-backed table artifacts and deterministic paper repair."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from ..utils.atomic_write import atomic_write_bytes
from .paper_evidence import (
    MetricEvidence as MetricEvidence,
    PaperEvidence as PaperEvidence,
    _read as _read,
    _read_json_object as _read_json_object,
    _read_yaml_object as _read_yaml_object,
    _latex as _latex,
    _publication_text as _publication_text,
    _first_publication_text as _first_publication_text,
    _figure_publication_caption as _figure_publication_caption,
    _table_plain_text as _table_plain_text,
    _table_source_matches_registered_rows as _table_source_matches_registered_rows,
    _extract_title as _extract_title,
    _collect_metrics as _collect_metrics,
)


_PENDING_SIGNAL = re.compile(
    r"(?:not\s+run|pending|no\s+(?:actual\s+)?(?:metric|result)|尚未|待运行|待完成|未运行)",
    re.IGNORECASE,
)
_PLACEHOLDER_SIGNAL = re.compile(
    r"(?:lorem ipsum|your paper title|your abstract here|todo\b|placeholder|"
    r"insert (?:text|figure|table)|待补充|此处填写)",
    re.IGNORECASE,
)
_CJK_SIGNAL = re.compile(
    r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]"
)
_PUBLICATION_META_SIGNAL = re.compile(
    r"\b(?:publication-facing|implementation bookkeeping|status language|"
    r"layout-only repair|renderer|internal planning|workflow status)\b",
    re.IGNORECASE,
)
TABLE_MANIFEST_SCHEMA = 3

# A paper freeze must bind scientific meaning, not renderer bookkeeping. The
# table/figure builders update these fields whenever a PDF/SVG/LaTeX asset is
# re-laid out. Keeping the policy next to the manifest code makes it usable by
# both the acceptance gate and the staged-paper freeze.
DERIVED_RENDERER_FIELDS = frozenset({
    "updated_at",
    "generated_at",
    "created_at",
    "modified_at",
    "output_sha256",
    "source_sha256",
    "preview_sha256",
    "sha256",
    "content_sha256",
    "rendered_variant_sha256",
    "protocol_artifact_sha256",
    "simulation_manifest_sha256",
    "paper_figures_sha256",
    "renderer_sha256",
    "render_sha256",
    "figure_manifest_sha256",
})

# Simulation manifests contain both the scientific benchmark contract and
# renderer-owned bookkeeping (timestamps, output hashes, figure/table
# previews). Keep a dedicated projection so that a renderer refresh cannot
# invalidate an otherwise unchanged synthetic result analysis. Data-file
# hashes remain bound because they identify machine-readable metric rows.
SIMULATION_RENDERER_FIELDS = frozenset({
    "generated_at",
    "renderer_version",
    "figure_files",
    "visual_quality",
    "paper_table",
    "paper_table_sha256",
    "paper_figures",
    "paper_figures_sha256",
})


def simulation_manifest_semantic_payload(payload: Any) -> Any:
    """Return the stable scientific projection of a simulation manifest.

    ``SIMULATION_MANIFEST.json`` is also a renderer registry. Generated
    timestamps and preview hashes legitimately change when figures/tables are
    re-rendered, but benchmark identity, contracts, and CSV data hashes remain
    frozen. This projection preserves ``sha256`` only under ``data_files``.
    """

    def project(value: Any, *, data_file: bool = False) -> Any:
        if isinstance(value, dict):
            projected: dict[str, Any] = {}
            for key in sorted(value):
                key_text = str(key)
                if (
                    key_text in SIMULATION_RENDERER_FIELDS
                    or (
                        key_text in DERIVED_RENDERER_FIELDS
                        and not (data_file and key_text == "sha256")
                    )
                ):
                    continue
                if not data_file and key_text == "sha256":
                    continue
                projected[key_text] = project(
                    value[key],
                    data_file=data_file or key_text == "data_files",
                )
            return projected
        if isinstance(value, list):
            projected_list = [project(item, data_file=data_file) for item in value]
            if data_file and all(isinstance(item, dict) for item in projected_list):
                return sorted(
                    projected_list,
                    key=lambda item: str(item.get("path") or ""),
                )
            return projected_list
        return value

    return project(payload)


def simulation_manifest_semantic_hash(payload: Any) -> str:
    """Hash the stable scientific simulation-manifest projection."""
    return hashlib.sha256(
        json.dumps(
            simulation_manifest_semantic_payload(payload),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _semantic_manifest_value(value: Any, *, table_manifest: bool = False) -> Any:
    """Return a deterministic, renderer-independent JSON projection.

    Scientific fields such as data hashes, labels, captions, roles,
    source_data, provenance, and uncertainty declarations remain bound.
    Only explicitly renderer-owned fields are removed.
    """
    if isinstance(value, dict):
        projected: dict[str, Any] = {}
        for key in sorted(value):
            key_text = str(key)
            if key_text in DERIVED_RENDERER_FIELDS:
                continue
            # A table's LaTeX hash is a rendering identity. The table's data
            # hash and all semantic descriptors are intentionally retained.
            if table_manifest and key_text == "latex_sha256":
                continue
            projected[key_text] = _semantic_manifest_value(
                value[key], table_manifest=table_manifest
            )
        return projected
    if isinstance(value, list):
        return [
            _semantic_manifest_value(item, table_manifest=table_manifest)
            for item in value
        ]
    return value


def semantic_derived_payload(relative_path: str, payload: Any) -> Any:
    """Project one derived artifact to the portion that defines science."""
    normalized = str(relative_path or "").replace("\\", "/").casefold()
    return _semantic_manifest_value(
        payload,
        table_manifest=normalized.endswith("paper/tables/table_manifest.json"),
    )


def semantic_derived_hash(relative_path: str, payload: Any) -> str:
    projected = semantic_derived_payload(relative_path, payload)
    return hashlib.sha256(
        json.dumps(
            projected,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def bind_table_manifest_hashes(
    project_path: str | Path,
    payload: dict[str, Any],
) -> tuple[dict[str, Any], list[str], bool]:
    """Validate current table bindings without changing hashes or schema.

    Only the producer may initialize hashes through ``build_table_manifest``.
    Consumers cannot accept a changed table by rebinding it during validation.
    """
    root = Path(project_path).expanduser().resolve()
    from .paper_table_projection_validation import table_publication_projection_issues
    bound = dict(payload or {})
    raw_tables = bound.get("tables")
    tables = [dict(item) for item in raw_tables or [] if isinstance(item, dict)]
    issues: list[str] = []
    changed = False
    if bound.get("schema") != TABLE_MANIFEST_SCHEMA:
        issues.append("table manifest schema is unsupported")

    for item in tables:
        table_id = str(item.get("id") or "unknown")
        issues.extend(f"table {table_id}: {issue}" for issue in table_publication_projection_issues(root, item))
        for path_key, hash_key in (
            ("data_path", "data_sha256"),
            ("latex_path", "latex_sha256"),
        ):
            raw_path = str(item.get(path_key) or "").strip()
            if not raw_path:
                issues.append(f"table {table_id} has no {path_key}")
                continue
            candidate = Path(raw_path).expanduser()
            candidate = candidate if candidate.is_absolute() else root / candidate
            try:
                candidate = candidate.resolve()
                candidate.relative_to(root)
            except (OSError, ValueError):
                issues.append(f"table {table_id} {path_key} escapes project")
                continue
            if not candidate.is_file() or candidate.stat().st_size <= 0:
                issues.append(f"table {table_id} {path_key} is missing: {raw_path}")
                continue
            current = hashlib.sha256(candidate.read_bytes()).hexdigest()
            expected = str(item.get(hash_key) or "").strip()
            if not expected:
                issues.append(f"table {table_id} has no {hash_key}")
            elif expected != current:
                issues.append(f"table {table_id} {hash_key} does not match {raw_path}")

    bound["tables"] = tables
    return bound, issues, changed


def build_table_manifest(
    project_path: str | Path, tables: list[dict[str, Any]],
) -> dict[str, Any]:
    """Initialize runtime-owned hashes for tables freshly written by their owner."""
    root = Path(project_path).expanduser().resolve()
    records = [dict(item) for item in tables]
    for item in records:
        for path_key, hash_key in (
            ("data_path", "data_sha256"), ("latex_path", "latex_sha256"),
        ):
            relative = str(item.get(path_key) or "").strip()
            if not relative:
                raise ValueError(f"table {item.get('id')} has no {path_key}")
            candidate = (root / relative).resolve()
            try:
                candidate.relative_to(root)
            except ValueError as error:
                raise ValueError(f"table {item.get('id')} {path_key} escapes project") from error
            if not candidate.is_file() or candidate.stat().st_size <= 0:
                raise ValueError(f"table {item.get('id')} {path_key} is missing")
            item[hash_key] = hashlib.sha256(candidate.read_bytes()).hexdigest()
    payload = {"schema": TABLE_MANIFEST_SCHEMA, "tables": records}
    _, issues, _ = bind_table_manifest_hashes(root, payload)
    if issues:
        raise ValueError("; ".join(issues))
    return payload


class PaperArtifactBuilder:
    """Build durable tables and repair papers from project evidence."""

    def snapshot(
        self,
        project_path: str | Path,
        direction: str = "",
    ) -> PaperEvidence:
        from .paper_evidence_snapshot import collect_paper_evidence

        return collect_paper_evidence(project_path, direction)

    @staticmethod
    def _figure_priority(
        item: dict[str, Any],
        has_metrics: bool,
    ) -> tuple[int, str]:
        from .paper_evidence_snapshot import figure_priority

        return figure_priority(item, has_metrics)

    def prepare(self, project_path: str | Path, direction: str = "") -> PaperEvidence:
        evidence = self.snapshot(project_path, direction)
        paper_dir = evidence.root / "paper"
        paper_dir.mkdir(parents=True, exist_ok=True)
        source_bib = evidence.root / "literature" / "references.bib"
        if source_bib.exists():
            atomic_write_bytes(
                paper_dir / "references.bib",
                source_bib.read_bytes(),
            )
        self._write_submission_tables(evidence)
        self._write_figures(evidence)
        self._write_snapshot(evidence)
        self.refresh_evidence_map(evidence.root, evidence)
        return evidence

    @staticmethod
    def _backup_main(main_path: Path) -> None:
        if not main_path.exists() or main_path.stat().st_size == 0:
            return
        digest = hashlib.sha256(main_path.read_bytes()).hexdigest()[:10]
        revisions = main_path.parent / "revisions"
        revisions.mkdir(parents=True, exist_ok=True)
        backup = revisions / f"model_draft_{digest}.tex"
        if not backup.exists():
            atomic_write_bytes(backup, main_path.read_bytes())

    @staticmethod
    def has_substantive_draft(project_path: str | Path) -> bool:
        main_path = Path(project_path).expanduser().resolve() / "paper" / "main.tex"
        content = _read(main_path, 250000)
        return bool(
            len(content) >= 4000
            and "\\documentclass" in content
            and "\\begin{document}" in content
            and "\\end{document}" in content
            and len(re.findall(r"\\section\*?\{", content)) >= 5
            and not _PLACEHOLDER_SIGNAL.search(content)
        )

    def _write_submission_tables(self, evidence: PaperEvidence) -> None:
        from .paper_submission_tables import write_submission_tables

        write_submission_tables(evidence)
    def refresh_evidence_map(
        self,
        project_path: str | Path,
        evidence: PaperEvidence | None = None,
    ) -> Path:
        from .paper_evidence_map import refresh_paper_evidence_map

        resolved = evidence or self.snapshot(project_path)
        return refresh_paper_evidence_map(resolved)
    def _write_figures(self, evidence: PaperEvidence) -> None:
        from .paper_figure_outputs import write_paper_figure_bundles

        write_paper_figure_bundles(evidence)
    def _write_snapshot(self, evidence: PaperEvidence) -> None:
        from .paper_evidence_output import write_evidence_snapshot

        write_evidence_snapshot(evidence)
    def augment_existing(self, evidence: PaperEvidence) -> bool:
        from .paper_existing_augmentation import augment_existing_manuscript

        return augment_existing_manuscript(evidence, self._backup_main)
    def write_fallback(self, evidence: PaperEvidence) -> Path:
        from .paper_fallback_manuscript import write_fallback_manuscript

        return write_fallback_manuscript(evidence, self._backup_main)


paper_artifact_builder = PaperArtifactBuilder()
