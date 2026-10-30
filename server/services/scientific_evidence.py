"""Cross-check machine-readable metrics against runtime-owned execution evidence."""

from __future__ import annotations

from pathlib import Path

from .execution_provenance import execution_provenance_service
from .paper_artifacts import _collect_metrics
from .scientific_assets import scientific_asset_service

class ScientificEvidenceService:
    """Reject metrics that cannot be tied to a successful tool-owned run."""

    def validate_executed_metrics(self, project_path: str | Path) -> tuple[bool, list[str], dict]:
        root = Path(project_path).expanduser().resolve()
        # Evidence validation must be read-only. Paper snapshot reconciliation
        # can rewrite a figure manifest, which is unrelated to metric
        # provenance and can invalidate downstream source hashes.
        metrics = _collect_metrics(root)
        qualitative_records = scientific_asset_service.collect_qualitative_records(
            root
        )
        issues: list[str] = []
        if not metrics and not qualitative_records:
            issues.append(
                "no machine-readable scientific metric or traceable qualitative "
                "evidence record was found in experiments/results or experiments/logs"
            )

        events = [
            event for event in execution_provenance_service.load(root)
            if event.get("success") and event.get("tool") in {"Bash", "ssh_exec", "ssh_deploy"}
        ]
        managed_runs = execution_provenance_service.managed_runs(root)
        imported_sources = execution_provenance_service.imported_sources(root)
        if not events and not managed_runs and not imported_sources:
            issues.append(
                "no successful runtime-owned experiment execution event, "
                "managed run manifest, or hash-verified evidence import was recorded"
            )

        evidence_suffixes = {
            Path(item.source).suffix.casefold()
            for item in [*metrics, *qualitative_records]
            if Path(item.source).suffix
        } or {".csv", ".tsv", ".json", ".npz"}
        all_proven_sources = execution_provenance_service.proven_result_sources(
            root,
            suffixes=evidence_suffixes,
        )
        proven_sources: set[str] = set()
        for metric in metrics:
            source = root / metric.source
            if not source.exists() or not source.is_file():
                continue
            if metric.source in all_proven_sources:
                proven_sources.add(metric.source)
        qualitative_sources = {
            item.source for item in qualitative_records
            if item.source in all_proven_sources
        }
        proven_sources.update(qualitative_sources)
        if (metrics or qualitative_records) and not proven_sources:
            issues.append(
                "scientific evidence files are not hash-linked to a successful "
                "execution event"
            )

        details = {
            "metric_count": len(metrics),
            "metric_sources": sorted({metric.source for metric in metrics}),
            "qualitative_record_count": len(qualitative_records),
            "qualitative_sources": sorted({
                item.source for item in qualitative_records
            }),
            "proven_sources": sorted(proven_sources),
            "execution_events": len(events),
            "managed_runtime_manifests": len(managed_runs),
            "managed_runtime_ids": [
                str(item.get("run_id") or "") for item in managed_runs
            ],
            "imported_sources": sorted(imported_sources),
        }
        return not issues, issues, details


scientific_evidence_service = ScientificEvidenceService()
