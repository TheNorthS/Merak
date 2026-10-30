"""Planned-result templates for workflows that intentionally skip experiment execution."""

from __future__ import annotations

import csv
import hashlib
import io
import re
from pathlib import Path
from typing import Any

from .publication_labels import (
    publication_component_label as _publication_component_label,  # noqa: F401
    publication_metric_label as _publication_metric_label,  # noqa: F401
    publication_outcome_label as _publication_outcome_label,  # noqa: F401
)
from .experiment_placeholder_context import (
    components as _context_components,
    context as _research_context,
    infer_primary_metric as _infer_primary_metric,
    input_bundle_sha256 as _input_bundle_sha256,
    json_object as _json_object,
    label as _display_label,
    metric_direction as _metric_direction,
    normalized_metric_direction as _normalized_metric_direction,
    robustness_axis as _robustness_axis,
    simulation_domain_context as _simulation_domain_context,
    yaml_object as _yaml_object,
)
from .simulation_statistics import paired_t_two_sided_p as _paired_t_two_sided_p  # noqa: F401
from .simulation_asset_profile import simulation_asset_profile
from .simulation_artifact_io import (
    clear_simulation_preview,
    render_simulation_script,
    simulation_figures_tex,
)
from .planned_result_tables import planned_result_tables
from .simulation_table_projection import simulation_tables
from .simulation_comparison_plots import (
    _ablation_delta_script,
    _bar_script,
    _multitask_matrix_script,
    _robustness_script,
)
from .simulation_diagnostic_plots import (
    _domain_error_heatmap_script,
    _eeg_scaling_script,
    _eeg_shift_script,
    _risk_coverage_script,
    _slice_risk_bar_script,
)
from .simulation_efficiency_plots import (
    _domain_efficiency_script,
    _efficiency_script,
)
from ..utils.atomic_write import atomic_write_text


_CJK_SIGNAL = re.compile(
    r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]"
)


def _latex(value: str) -> str:
    return (
        value.replace("\\", r"\textbackslash{}")
        .replace("&", r"\&")
        .replace("%", r"\%")
        .replace("#", r"\#")
        .replace("_", r"\_")
    )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class ExperimentPlaceholderService:
    """Create blank, replaceable schemas without inventing quantitative evidence."""

    input_bundle_sha256 = staticmethod(_input_bundle_sha256)
    _context = staticmethod(_research_context)
    _simulation_domain_context = staticmethod(_simulation_domain_context)
    _components = staticmethod(_context_components)
    _json_object = staticmethod(_json_object)
    _yaml_object = staticmethod(_yaml_object)
    _label = staticmethod(_display_label)
    _normalized_metric_direction = staticmethod(_normalized_metric_direction)
    _metric_direction = staticmethod(_metric_direction)
    _infer_primary_metric = staticmethod(_infer_primary_metric)
    _robustness_axis = staticmethod(_robustness_axis)
    _simulation_asset_profile = staticmethod(simulation_asset_profile)

    @staticmethod
    def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
        if not rows:
            return
        saved: dict[str, dict[str, str]] = {}
        if path.is_file():
            try:
                with path.open("r", encoding="utf-8-sig", newline="") as handle:
                    saved = {
                        row["row_id"]: dict(row)
                        for row in csv.DictReader(handle)
                        if row.get("row_id")
                    }
            except (OSError, csv.Error):
                saved = {}
        for row in rows:
            previous = saved.get(row["row_id"], {})
            for key, value in previous.items():
                if (
                    key in row
                    and str(value or "").strip()
                    and key not in {
                        "row_id",
                        "method",
                        "component_setting",
                        "metric",
                        "metric_direction",
                        "ablation_group",
                        "simulation_kind",
                        "simulation_seed",
                        "seed_count",
                        "seed_values",
                        "replicate_unit",
                    }
                    and not re.fullmatch(r"resource_\d+_label", key)
                ):
                    row[key] = value
        buffer = io.StringIO(newline="")
        fieldnames = list(rows[0])
        for row in rows[1:]:
            for key in row:
                if key not in fieldnames:
                    fieldnames.append(key)
        writer = csv.DictWriter(buffer, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
        atomic_write_text(path, buffer.getvalue(), encoding="utf-8-sig")

    _bar_script = staticmethod(_bar_script)
    _robustness_script = staticmethod(_robustness_script)
    _ablation_delta_script = staticmethod(_ablation_delta_script)
    _multitask_matrix_script = staticmethod(_multitask_matrix_script)
    _eeg_scaling_script = staticmethod(_eeg_scaling_script)
    _domain_error_heatmap_script = staticmethod(_domain_error_heatmap_script)
    _domain_efficiency_script = staticmethod(_domain_efficiency_script)
    _eeg_shift_script = staticmethod(_eeg_shift_script)
    _slice_risk_bar_script = staticmethod(_slice_risk_bar_script)
    _risk_coverage_script = staticmethod(_risk_coverage_script)
    _efficiency_script = staticmethod(_efficiency_script)


    _render = staticmethod(render_simulation_script)

    _tables = staticmethod(planned_result_tables)

    _simulation_tables = staticmethod(simulation_tables)

    _simulation_figures_tex = staticmethod(simulation_figures_tex)
    _clear_simulation_preview = staticmethod(clear_simulation_preview)

    async def _build_simulation_preview(
        self,
        *,
        root: Path,
        publication_style: dict[str, Any],
        research_context: str = "",
        direction: str = "",
        main_rows: list[dict[str, str]],
        ablation_rows: list[dict[str, str]],
        robustness_rows: list[dict[str, str]],
        calibration_rows: list[dict[str, str]],
        efficiency_rows: list[dict[str, str]],
        claim_ids: list[str],
        axis: str,
        primary_metric: str,
        metric_direction: str,
        validation_curve_labels: tuple[str, str],
    ) -> dict[str, Any]:
        from .simulation_benchmark import build_simulation_benchmark

        return await build_simulation_benchmark(
            self, root=root, publication_style=publication_style, direction=direction,
            main_rows=main_rows, ablation_rows=ablation_rows, robustness_rows=robustness_rows,
            calibration_rows=calibration_rows, efficiency_rows=efficiency_rows, claim_ids=claim_ids,
            axis=axis, primary_metric=primary_metric, metric_direction=metric_direction,
            validation_curve_labels=validation_curve_labels,
        )

    async def ensure(
        self,
        project_path: str | Path,
        direction: str = "",
        *,
        evidence_mode: str = "design_only",
        target_venue: str = "",
        research_family: str = "",
        study_archetype: str = "",
    ) -> dict[str, Any]:
        from .planned_result_coordinator import ensure_planned_results

        return await ensure_planned_results(
            self, project_path, direction, evidence_mode=evidence_mode,
            target_venue=target_venue, research_family=research_family,
            study_archetype=study_archetype,
        )


experiment_placeholder_service = ExperimentPlaceholderService()
