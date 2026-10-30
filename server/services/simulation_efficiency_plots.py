"""Plot-script builders for scientific resource and efficiency trade-offs."""

from __future__ import annotations

from typing import Any

from .simulation_plot_template import render_plot_template

def _domain_efficiency_script(
    data_path: str,
    metric: str,
    style: dict[str, Any],
    stem: str,
) -> str:
    """Render the efficiency audit as paired parameter/FLOPs frontiers."""
    palette = dict(style.get("palette") or {})
    canvas = dict(style.get("canvas") or {})
    fonts = list(style.get("fonts") or ["Arial", "Helvetica", "DejaVu Sans"])
    blue = str(palette.get("blue") or "#0072B2")
    orange = str(palette.get("orange") or "#E69F00")
    grey = str(palette.get("grey") or "#6B7280")
    width = float(canvas.get("double_column_inches") or 7.2)
    font_size = float(canvas.get("target_font_pt") or 8.0)
    dpi = int(canvas.get("png_dpi") or 450)
    tick_font_size = max(5.0,font_size-1.0)
    panel_font_size = max(6.5,font_size-0.1)
    return render_plot_template("domain_efficiency", locals())

def _efficiency_script(
    data_path: str,
    metric: str,
    resource_field: str,
    resource_label: str,
    style: dict[str, Any],
    output_stem: str = "efficiency_tradeoff_preview",
    metric_direction: str = "maximize",
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
    annotation_font_size = max(7.5, font_size - 0.4)
    panel_label_font_size = max(8.5, font_size + 0.5)
    return render_plot_template("efficiency", locals())
