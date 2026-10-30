"""Select provenance-backed primary, qualitative, and secondary evidence."""

from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import Any

from .execution_provenance import execution_provenance_service
from .scientific_record_models import QualitativeEvidenceRecord, ResultRecord


class ScientificEvidenceSourcesMixin:
    @staticmethod
    def _proven_sources(root: Path) -> set[str]:
        return execution_provenance_service.proven_result_sources(
            root, suffixes={".csv", ".json"}
        )

    def collect_records(self, project_path: str | Path) -> list[ResultRecord]:
        from .scientific_assets import _NON_SCIENTIFIC_PATH

        root = Path(project_path).expanduser().resolve()
        results_root = root / "experiments" / "results"
        if not results_root.exists():
            return []
        proven = self._proven_sources(root)
        from .scientific_matrix_records import matrix_aggregate_records, administrative_result_file
        matrix = matrix_aggregate_records(self, root, proven)
        if matrix is not None:
            return matrix
        records: list[ResultRecord] = []
        for path in sorted(results_root.rglob("*")):
            if not path.is_file() or path.stat().st_size == 0:
                continue
            if administrative_result_file(path):
                continue
            relative = path.relative_to(root).as_posix()
            if relative not in proven or _NON_SCIENTIFIC_PATH.search(relative):
                continue
            if path.suffix.lower() == ".csv":
                records.extend(self._records_from_csv(root, path))
            elif path.suffix.lower() == ".json":
                records.extend(self._records_from_json(root, path))
        unique = {_record_identity(item): item for item in records}
        return list(unique.values())

    def collect_qualitative_records(
        self, project_path: str | Path
    ) -> list[QualitativeEvidenceRecord]:
        from .scientific_assets import _NON_SCIENTIFIC_PATH

        root = Path(project_path).expanduser().resolve()
        results_root = root / "experiments" / "results"
        if not results_root.exists():
            return []
        proven = self._proven_sources(root)
        records: list[QualitativeEvidenceRecord] = []
        for path in sorted(results_root.rglob("*.csv")):
            relative = path.relative_to(root).as_posix()
            if relative not in proven or _NON_SCIENTIFIC_PATH.search(relative):
                continue
            for row in _read_csv(path):
                record = _qualitative_record(row, relative)
                if record is not None:
                    records.append(record)
        unique = {
            (item.theme, item.case, item.evidence, item.source, item.source_id): item
            for item in records
        }
        return list(unique.values())

    def collect_secondary_records(
        self, project_path: str | Path
    ) -> tuple[list[ResultRecord], list[str], list[str]]:
        from .scientific_assets import _json

        root = Path(project_path).expanduser().resolve()
        manifest = _json(
            root / "experiments" / "results" / "SECONDARY_EVIDENCE.json"
        )
        if not manifest:
            return [], [
                "Secondary analysis requires experiments/results/SECONDARY_EVIDENCE.json."
            ], []
        sources = manifest.get("sources")
        if not isinstance(sources, list) or not sources:
            return [], [
                "SECONDARY_EVIDENCE.json must contain a non-empty sources list."
            ], []
        bibliography = _bibliography(root)
        records: list[ResultRecord] = []
        issues: list[str] = []
        accepted: list[str] = []
        for index, item in enumerate(sources, start=1):
            candidate, issue = _validated_secondary_source(
                root, item, index, bibliography
            )
            if issue:
                issues.append(issue)
                continue
            if candidate.suffix.casefold() == ".csv":
                records.extend(self._records_from_csv(root, candidate))
            else:
                records.extend(self._records_from_json(root, candidate))
            accepted.append(candidate.relative_to(root).as_posix())
        if accepted and not records:
            issues.append(
                "Verified secondary sources contain no parseable completed metric records."
            )
        return records, issues, accepted


def _record_identity(record: ResultRecord) -> tuple[Any, ...]:
    return (
        record.method, record.metric, record.value, record.source, record.seed,
        record.split, record.condition_name, record.condition_value, record.role,
        record.ci_low, record.ci_high, record.unit, record.estimate_type,
        record.p_value, record.adjusted_p,
    )


def _read_csv(path: Path) -> list[dict[str, Any]]:
    try:
        with path.open(
            "r", encoding="utf-8-sig", errors="replace", newline=""
        ) as handle:
            return list(csv.DictReader(handle))
    except (OSError, csv.Error):
        return []


def _qualitative_record(
    row: dict[str, Any], source: str
) -> QualitativeEvidenceRecord | None:
    from .scientific_assets import _clean_name, _first

    status = str(_first(row, ("status", "run_status"))).casefold()
    if status and status not in {
        "complete", "completed", "success", "succeeded",
        "executed", "accepted", "done",
    }:
        return None
    theme = _clean_name(
        _first(row, ("theme", "code", "category", "finding")), "", 160
    )
    evidence = _clean_name(
        _first(row, (
            "evidence", "excerpt", "quote", "observation",
            "supporting_text", "analytic_memo",
        )),
        "", 600,
    )
    case = _clean_name(
        _first(row, (
            "case", "participant", "document", "site", "corpus_item",
            "source_id", "record_id",
        )),
        "Unspecified case", 120,
    )
    if not theme or not evidence:
        return None
    return QualitativeEvidenceRecord(
        theme=theme, case=case, evidence=evidence, source=source,
        source_id=_clean_name(
            _first(row, ("source_id", "record_id", "document_id")), case, 120
        ),
        polarity=_clean_name(
            _first(row, ("polarity", "valence", "stance")), "", 60
        ),
        coder=_clean_name(
            _first(row, ("coder", "analyst", "reviewer")), "", 80
        ),
        triangulation_source=_clean_name(
            _first(row, (
                "triangulation_source", "source_type", "evidence_type",
            )),
            "", 100,
        ),
    )


def _bibliography(root: Path) -> str:
    path = root / "literature" / "references.bib"
    return path.read_text(encoding="utf-8", errors="replace") if path.is_file() else ""


def _validated_secondary_source(
    root: Path, item: Any, index: int, bibliography: str
) -> tuple[Path, str]:
    from .scientific_assets import _sha256

    if not isinstance(item, dict):
        return root, f"Secondary source {index} is not an object."
    relative = str(item.get("data_path") or "").strip().replace("\\", "/")
    citation = str(item.get("citation_key") or "").strip()
    locator = str(item.get("source_url") or item.get("doi") or "").strip()
    expected_hash = str(item.get("sha256") or "").strip().casefold()
    candidate = (root / relative).resolve() if relative else root
    results_root = (root / "experiments" / "results").resolve()
    try:
        candidate.relative_to(results_root)
    except ValueError:
        return candidate, (
            f"Secondary source {index} escapes experiments/results: "
            f"{relative or '<missing>'}."
        )
    if (
        not candidate.is_file() or candidate.stat().st_size == 0
        or candidate.suffix.casefold() not in {".csv", ".json"}
    ):
        return candidate, (
            f"Secondary source {index} is missing or unsupported: "
            f"{relative or '<missing>'}."
        )
    if len(expected_hash) != 64 or _sha256(candidate) != expected_hash:
        return candidate, f"Secondary source {index} SHA256 does not match: {relative}."
    valid_locator = bool(
        locator.casefold().startswith(("http://", "https://", "doi:"))
        or re.fullmatch(r"10\.\d{4,9}/\S+", locator)
    )
    if not locator or not valid_locator:
        return candidate, (
            f"Secondary source {index} has no valid source URL or DOI: {relative}."
        )
    if not citation or not re.search(
        rf"(?im)^\s*@[a-z]+\s*\{{\s*{re.escape(citation)}\s*,", bibliography
    ):
        return candidate, (
            f"Secondary source {index} citation key is absent from "
            f"literature/references.bib: {citation or '<missing>'}."
        )
    return candidate, ""
