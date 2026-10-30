"""Plot-script builders for comparisons, ablations, and multi-task results."""

from __future__ import annotations

from typing import Any

from .simulation_plot_template import render_plot_template

def _bar_script(
    data_path: str,
    label_field: str,
    metric: str,
    stem: str,
    style: dict[str, Any],
    highlight_label: str = "",
    variant: str = "ranked",
) -> str:
    palette = dict(style.get("palette") or {})
    canvas = dict(style.get("canvas") or {})
    fonts = list(style.get("fonts") or ["Arial", "Helvetica", "DejaVu Sans"])
    accent = str(palette.get("blue") or "#0072B2")
    neutral = str(palette.get("grey") or "#6B7280")
    dark = str(palette.get("black") or "#222222")
    width = float(canvas.get("double_column_inches") or 7.2)
    font_size = float(canvas.get("target_font_pt") or 8.0)
    dpi = int(canvas.get("png_dpi") or 450)
    tick_font_size = max(5.0, font_size - 0.5)
    annotation_font_size = max(5.5, font_size - 0.6)
    return render_plot_template("bar", locals())

def _robustness_script(
    data_path: str,
    axis: str,
    metric: str,
    style: dict[str, Any],
    output_stem: str = "robustness_curve_preview",
) -> str:
    palette = dict(style.get("palette") or {})
    canvas = dict(style.get("canvas") or {})
    fonts = list(style.get("fonts") or ["Arial", "Helvetica", "DejaVu Sans"])
    colors = [
        str(palette.get("grey") or "#6B7280"),
        str(palette.get("blue") or "#0072B2"),
        str(palette.get("orange") or "#E69F00"),
        str(palette.get("green") or "#009E73"),
        str(palette.get("vermillion") or "#D55E00"),
    ]
    width = float(canvas.get("double_column_inches") or 7.2)
    font_size = float(canvas.get("target_font_pt") or 8.0)
    dpi = int(canvas.get("png_dpi") or 450)
    tick_font_size = max(5.0, font_size - 0.5)
    return render_plot_template("robustness", locals())

def _ablation_delta_script(
    data_path: str,
    label_field: str,
    metric: str,
    stem: str,
    style: dict[str, Any],
    baseline_label: str,
    metric_direction: str,
) -> str:
    """Render component removals as losses from the registered full method."""
    palette = dict(style.get("palette") or {})
    canvas = dict(style.get("canvas") or {})
    fonts = list(style.get("fonts") or ["Arial", "Helvetica", "DejaVu Sans"])
    accent = str(palette.get("vermillion") or "#D55E00")
    baseline = str(palette.get("blue") or "#0072B2")
    neutral = str(palette.get("grey") or "#6B7280")
    objective = str(palette.get("orange") or "#E69F00")
    architecture = str(palette.get("green") or "#009E73")
    protocol = str(palette.get("purple") or "#CC79A7")
    dark = str(palette.get("black") or "#222222")
    width = float(canvas.get("double_column_inches") or 7.2)
    font_size = float(canvas.get("target_font_pt") or 8.0)
    dpi = int(canvas.get("png_dpi") or 450)
    tick_font_size = max(5.0, font_size - 0.5)
    annotation_font_size = max(5.5, font_size - 0.6)
    return render_plot_template("ablation_delta", locals())

def _multitask_matrix_script(
    data_path: str,
    metric: str,
    stem: str,
    style: dict[str, Any],
    metric_direction: str,
) -> str:
    """Render domain benchmark results as a dataset-by-task matrix.

    CBraMod's strongest visual evidence is not one aggregate bar chart but
    repeated, comparable panels for each downstream task. This renderer
    applies that grammar to any detected domain while preserving the
    provenance/CI contract and exposing heterogeneity that a pooled forest hides.
    """
    palette = dict(style.get("palette") or {})
    canvas = dict(style.get("canvas") or {})
    fonts = list(style.get("fonts") or ["Arial", "Helvetica", "DejaVu Sans"])
    colors = [
        str(palette.get("grey") or "#6B7280"),
        str(palette.get("blue") or "#0072B2"),
        str(palette.get("orange") or "#E69F00"),
        str(palette.get("green") or "#009E73"),
        str(palette.get("vermillion") or "#D55E00"),
        str(palette.get("purple") or "#CC79A7"),
    ]
    width = float(canvas.get("double_column_inches") or 7.2)
    font_size = float(canvas.get("target_font_pt") or 8.0)
    dpi = int(canvas.get("png_dpi") or 450)
    tick_font_size = max(5.0, font_size - 0.7)
    legend_font_size = max(5.0, font_size - 0.8)
    small_font_size = max(5.0, font_size - 1.0)
    panel_font_size = max(6.2, font_size - 0.2)
    return render_plot_template("multitask_matrix", locals())
