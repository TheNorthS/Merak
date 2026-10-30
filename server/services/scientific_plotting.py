"""Build executable, field-adaptive scientific plotting scripts.

The workflow persists each returned script next to the rendered PDF/SVG/PNG.
Dispatch is based on the publication contract and on columns actually present
in the aggregate table. Unsupported encodings fall back to an honest interval
plot instead of inventing dimensions.
"""

from __future__ import annotations

from typing import Any

from .publication_figure_labels import validate_publication_labels
from .scientific_plot_template import SCIENTIFIC_PLOT_TEMPLATE


CURVE_PLOTS = {
    "calibration",
    "cohort_sensitivity",
    "convergence",
    "decision_curve",
    "dose_response",
    "risk_coverage",
    "scaling",
    "scaling_curve",
    "sensitivity",
    "stress_curve",
    "tail_latency",
    "time_course",
    "time_to_event",
}
INTERVAL_PLOTS = {
    "bound_comparison",
    "coefficient_plot",
    "dot_interval",
    "forest_effect",
    "interval_comparison",
    "matched_control_comparison",
    "subgroup_forest",
}


def _metric_display_label(asset: dict[str, Any]) -> str:
    """Read the declared public metric without translating machine identifiers."""
    labels, issues = validate_publication_labels(asset.get("publication_labels"))
    if issues:
        raise ValueError("Scientific plot publication labels: " + "; ".join(issues))
    metrics = [item for item in labels if item.get("kind") == "metric"]
    if len(metrics) != 1:
        raise ValueError("Scientific plot requires exactly one authored metric label")
    return str(metrics[0]["display_text"]).strip()


def build_scientific_plot_script(
    asset: dict[str, Any],
    publication_style: dict[str, Any],
    *,
    idea: str = "",
) -> str:
    """Return a standalone matplotlib script bound to one asset and CSV."""
    data_path = str(asset.get("data_path") or "")
    metric = _metric_display_label(asset)
    canvas = dict(publication_style.get("canvas") or {})
    palette = [
        str(value)
        for value in dict(publication_style.get("palette") or {}).values()
        if str(value).startswith("#")
    ][:8] or ["#0072B2", "#E69F00", "#009E73", "#D55E00", "#CC79A7"]
    plot_type = str(
        asset.get("recommended_plot_type") or "interval_comparison"
    ).strip().casefold()
    context = {
        "idea": str(idea or ""),
        "scientific_question": str(asset.get("scientific_question") or ""),
        "intended_comparison": str(asset.get("intended_comparison") or ""),
        "research_family": str(publication_style.get("family") or ""),
        "study_archetype": str(publication_style.get("study_archetype") or ""),
        "evidence_status": str(asset.get("evidence_status") or ""),
        "source_metric": str(asset.get("metric") or ""),
    }
    requested_fonts = [
        str(item)
        for item in publication_style.get("fonts", [])
        if str(item).strip()
    ]
    font_family = next(
        (item for item in requested_fonts if item.startswith("DejaVu")),
        "DejaVu Sans",
    )
    style = {
        "font_size": max(10.0, float(canvas.get("target_font_pt") or 10.0)),
        "font_family": font_family,
        "palette": palette,
        "visual_standard": str(
            publication_style.get("visual_standard")
            or "field-adaptive-accessible-vector-v2"
        ),
    }
    replacements = {
        "__SCIENTIFIC_CONTEXT__": repr(context),
        "__PUBLICATION_STYLE__": repr(style),
        "__PLOT_TYPE__": repr(plot_type),
        "__METRIC__": repr(metric),
        "__CURVE_PLOTS__": repr(sorted(CURVE_PLOTS)),
        "__INTERVAL_PLOTS__": repr(sorted(INTERVAL_PLOTS)),
        "__DATA_PATH__": repr(data_path),
    }
    script = SCIENTIFIC_PLOT_TEMPLATE
    for marker, value in replacements.items():
        script = script.replace(marker, value)
    return script


__all__ = [
    "CURVE_PLOTS",
    "INTERVAL_PLOTS",
    "build_scientific_plot_script",
]
