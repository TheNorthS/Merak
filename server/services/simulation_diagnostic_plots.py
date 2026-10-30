"""Plot-script builders for progression, shift, error, and calibration analyses."""

from __future__ import annotations

from typing import Any

from .simulation_plot_template import render_plot_template

def _eeg_scaling_script(
    data_path: str,
    axis: str,
    metric: str,
    style: dict[str, Any],
    stem: str,
) -> str:
    """Render pre-training scale as a two-panel loss/performance figure."""
    palette = dict(style.get("palette") or {})
    canvas = dict(style.get("canvas") or {})
    fonts = list(style.get("fonts") or ["Arial", "Helvetica", "DejaVu Sans"])
    blue = str(palette.get("blue") or "#0072B2")
    orange = str(palette.get("orange") or "#E69F00")
    grey = str(palette.get("grey") or "#6B7280")
    width = float(canvas.get("double_column_inches") or 7.2)
    font_size = float(canvas.get("target_font_pt") or 8.0)
    dpi = int(canvas.get("png_dpi") or 450)
    tick_font_size = max(5.0,font_size-0.6)
    legend_font_size = max(5.0,font_size-0.8)
    panel_font_size = max(6.5,font_size-0.1)
    return render_plot_template("eeg_scaling", locals())

def _domain_error_heatmap_script(
    data_path: str,
    label_field: str,
    metric: str,
    stem: str,
    style: dict[str, Any],
) -> str:
    """Render a compact dataset-by-error heatmap, not a generic slice bar."""
    canvas = dict(style.get("canvas") or {})
    fonts = list(style.get("fonts") or ["Arial", "Helvetica", "DejaVu Sans"])
    width = float(canvas.get("double_column_inches") or 7.2)
    font_size = float(canvas.get("target_font_pt") or 8.0)
    dpi = int(canvas.get("png_dpi") or 450)
    tick_font_size = max(5.2,font_size-0.8)
    panel_font_size = max(6.5,font_size-0.1)
    return render_plot_template("domain_error_heatmap", locals())

def _eeg_shift_script(data_path: str, metric: str, stem: str, style: dict[str, Any]) -> str:
    """Render EEG device/session transfer as paired facets."""
    palette = dict(style.get("palette") or {})
    canvas = dict(style.get("canvas") or {})
    fonts = list(style.get("fonts") or ["Arial", "Helvetica", "DejaVu Sans"])
    colors = [str(palette.get(k) or d) for k, d in (("grey", "#6B7280"), ("blue", "#0072B2"), ("orange", "#E69F00"), ("green", "#009E73"), ("vermillion", "#D55E00"))]
    width = float(canvas.get("double_column_inches") or 7.2)
    fs = float(canvas.get("target_font_pt") or 8.0)
    dpi = int(canvas.get("png_dpi") or 450)
    panel_font_size = max(6.5,fs-0.1)
    title_font_size = max(7.0,fs+.3)
    return render_plot_template("eeg_shift", locals())

def _slice_risk_bar_script(
    data_path: str,
    label_field: str,
    metric: str,
    stem: str,
    style: dict[str, Any],
    overall_label: str,
) -> str:
    """Render heterogeneous slice risk as bars against an overall reference."""
    palette = dict(style.get("palette") or {})
    canvas = dict(style.get("canvas") or {})
    fonts = list(style.get("fonts") or ["Arial", "Helvetica", "DejaVu Sans"])
    colors = [
        str(palette.get("blue") or "#0072B2"),
        str(palette.get("orange") or "#E69F00"),
        str(palette.get("green") or "#009E73"),
        str(palette.get("vermillion") or "#D55E00"),
        str(palette.get("purple") or "#CC79A7"),
    ]
    dark = str(palette.get("black") or "#222222")
    width = float(canvas.get("double_column_inches") or 7.2)
    font_size = float(canvas.get("target_font_pt") or 8.0)
    dpi = int(canvas.get("png_dpi") or 450)
    tick_font_size = max(5.0, font_size - 0.5)
    annotation_font_size = max(5.5, font_size - 0.6)
    return render_plot_template("slice_risk_bar", locals())

def _risk_coverage_script(
    data_path: str,
    style: dict[str, Any],
    x_label: str = "Coverage",
    y_label: str = "Selective risk",
    output_stem: str = "calibration_risk_coverage_preview",
) -> str:
    palette = dict(style.get("palette") or {})
    canvas = dict(style.get("canvas") or {})
    fonts = list(style.get("fonts") or ["Arial", "Helvetica", "DejaVu Sans"])
    colors = [
        str(palette.get("grey") or "#6B7280"),
        str(palette.get("blue") or "#0072B2"),
        str(palette.get("orange") or "#E69F00"),
        str(palette.get("green") or "#009E73"),
    ]
    width = float(canvas.get("double_column_inches") or 7.2)
    font_size = float(canvas.get("target_font_pt") or 8.0)
    dpi = int(canvas.get("png_dpi") or 450)
    tick_font_size = max(5.0, font_size - 0.5)
    panel_font_size = max(6.5, font_size - 0.1)
    return render_plot_template("risk_coverage", locals())
