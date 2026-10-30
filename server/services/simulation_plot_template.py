"""Load and bind packaged plotting-script templates."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping


_TEMPLATE_DIRECTORY = Path(__file__).with_name("simulation_plot_templates")


def render_plot_template(name: str, values: Mapping[str, Any]) -> str:
    """Render one trusted package template using an explicit value mapping."""
    if not name.replace("_", "").isalnum():
        raise ValueError(f"invalid simulation plot template name: {name!r}")
    path = _TEMPLATE_DIRECTORY / f"{name}.py.tmpl"
    template = path.read_text(encoding="utf-8")
    bound = dict(values)
    style = bound.get('style') or {}
    canvas = style.get('canvas') or {}
    width = float(bound.get('width') or canvas.get('double_column_inches') or 7.2)
    placed_width = float(canvas.get('placed_width_inches') or 6.5)
    minimum = max(8.0, float(canvas.get('minimum_font_pt') or 8.0))
    native_minimum = minimum * max(1.0, width / placed_width)
    for key, value in list(bound.items()):
        if (key.endswith('font_size') or key == 'fs') and isinstance(value, (int, float)):
            bound[key] = max(native_minimum, value)
    from .simulation_plot_layout import wrap_plot_axis_text

    return wrap_plot_axis_text(template.format_map(bound))
