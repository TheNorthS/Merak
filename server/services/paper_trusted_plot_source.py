"""Project only exact current packaged plotting programs, never arbitrary scripts.

The source program must structurally match one trusted producer template. Safe
literal parameters retain labels, contrasts and data paths. Runtime adaptation
changes source-proven axes/population grouping, typography and read-only
project/output bindings; original programs and scientific estimates are never edited.
"""

from __future__ import annotations

import ast
import math
import re
import string
from pathlib import Path
from typing import Any

from .simulation_plot_template import _TEMPLATE_DIRECTORY


_TEMPLATES = ("bar", "ablation_delta", "multitask_matrix", "robustness", "risk_coverage",
              "slice_risk_bar", "eeg_scaling", "eeg_shift", "domain_error_heatmap",
              "domain_efficiency", "efficiency")
_LIST_FIELDS = {"fonts", "colors"}
_NUMBER_FIELDS = {"width", "dpi", "fs", "font_size", "tick_font_size", "annotation_font_size",
                  "legend_font_size", "small_font_size", "panel_font_size", "title_font_size",
                  "panel_label_font_size"}
_FONT_KEYS = {"font.size", "axes.labelsize", "axes.titlesize", "xtick.labelsize",
              "ytick.labelsize", "legend.fontsize", "figure.titlesize", "figure.labelsize"}


def match_trusted_plot(source: str) -> tuple[str, dict[str, Any], bytes]:
    """Reject any executable structure outside the current packaged plot producers."""
    from .paper_native_plot_source import match_native_plot
    native = match_native_plot(source)
    if native is not None:
        from .scientific_plot_template import SCIENTIFIC_PLOT_TEMPLATE
        return 'native_scientific', native, SCIENTIFIC_PLOT_TEMPLATE.encode()
    actual = ast.parse(source)
    for name in _TEMPLATES:
        template_bytes = (_TEMPLATE_DIRECTORY / f"{name}.py.tmpl").read_bytes()
        template = template_bytes.decode("utf-8")
        fields = {field for _text, field, _spec, _conversion in string.Formatter().parse(template) if field}
        markers = _markers(fields)
        probe = ast.parse(template.format_map(markers))
        from .simulation_plot_layout import wrap_plot_axis_text

        # Both are exact current packaged programs: the template and its text-only layout projection.
        for candidate in (probe, ast.parse(wrap_plot_axis_text(template.format_map(markers)))):
            captures: dict[str, Any] = {}
            if _match(candidate, actual, markers, captures) and _valid_parameters(captures):
                return name, captures, template_bytes
    raise ValueError("Paper typography projection requires an exact current trusted plotting template")


def projected_plot_source(source: str, root: Path, output_stem: Path, multiplier: float) -> tuple[str, str, bytes]:
    """Return a trusted bounded typography projection with no arbitrary execution paths."""
    if not math.isfinite(multiplier) or not 1.0 <= multiplier <= 4.0:
        raise ValueError("Paper plot font multiplier must stay in its bounded presentation range")
    name, captures, template_bytes = match_trusted_plot(source)
    if name == 'native_scientific':
        from .paper_native_plot_source import project_native_plot
        return project_native_plot(source, root, output_stem, multiplier)
    tree = ast.parse(template_bytes.decode("utf-8").format_map(captures))
    from .paper_plot_semantics_projection import project_plot_semantics

    tree = project_plot_semantics(tree, name, captures, root.resolve())
    tree = _TypographyProjection(root.resolve(), output_stem.resolve(), multiplier, name).visit(tree)
    from .paper_curve_layout import project_curve_legend
    tree = project_curve_legend(tree, name)
    from .paper_risk_layout import project_risk_layout
    tree = project_risk_layout(tree, name)
    ast.fix_missing_locations(tree)
    return ast.unparse(tree) + "\n", name, template_bytes


def _markers(fields: set[str]) -> dict[str, Any]:
    result = {}
    for index, field in enumerate(sorted(fields), 1):
        marker = f"MERAK_SAFE_LITERAL_{field}"
        result[field] = [marker] if field in _LIST_FIELDS else 19000.25 + index if field in _NUMBER_FIELDS else marker
    return result


def _capture(field: str, value: Any, captures: dict[str, Any]) -> bool:
    if field in captures and captures[field] != value:
        return False
    captures[field] = value
    return True


def _match(expected: Any, actual: Any, markers: dict[str, Any], captures: dict[str, Any]) -> bool:
    if isinstance(expected, ast.List) and len(expected.elts) == 1:
        marker = expected.elts[0]
        if isinstance(marker, ast.Constant):
            field = next((key for key, value in markers.items() if value == [marker.value]), "")
            if field:
                try:
                    return _capture(field, ast.literal_eval(actual), captures)
                except (ValueError, TypeError, SyntaxError):
                    return False
    if isinstance(expected, ast.Constant) and isinstance(actual, ast.Constant):
        field = next((key for key, value in markers.items() if not isinstance(value, list) and value == expected.value), "")
        if field:
            return _capture(field, actual.value, captures)
        if isinstance(expected.value, str) and isinstance(actual.value, str) and "MERAK_SAFE_LITERAL_" in expected.value:
            return _match_embedded(expected.value, actual.value, markers, captures)
        return expected.value == actual.value
    if isinstance(expected, ast.AST):
        return type(expected) is type(actual) and all(
            _match(getattr(expected, field), getattr(actual, field), markers, captures) for field in expected._fields
        )
    if isinstance(expected, list):
        return isinstance(actual, list) and len(expected) == len(actual) and all(
            _match(first, second, markers, captures) for first, second in zip(expected, actual, strict=True)
        )
    return expected == actual


def _match_embedded(expected: str, actual: str, markers: dict[str, Any], captures: dict[str, Any]) -> bool:
    fields = []
    pattern = re.escape(expected)
    for field, value in markers.items():
        if isinstance(value, str) and value in expected:
            fields.append(field)
            pattern = pattern.replace(re.escape(value), f"(?P<{field}>.*?)")
    match = re.fullmatch(pattern, actual, re.DOTALL)
    return bool(match) and all(_capture(field, match[field], captures) for field in fields)


def _valid_parameters(parameters: dict[str, Any]) -> bool:
    for key, value in parameters.items():
        if key in _NUMBER_FIELDS:
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
                return False
        elif key in _LIST_FIELDS:
            if not isinstance(value, list) or not value or any(not isinstance(item, str) for item in value):
                return False
        elif not isinstance(value, str) or any(token in value for token in ("\x00", "\r", "\n")):
            return False
    return bool(parameters.get("data_path"))


class _TypographyProjection(ast.NodeTransformer):
    """Only known font constants and deterministic filesystem bindings may change."""

    def __init__(self, root: Path, output: Path, multiplier: float, template: str):
        self.root, self.output, self.multiplier, self.template = root, output, multiplier, template

    def visit_Module(self, node: ast.Module):
        node = self.generic_visit(node)
        if not any(isinstance(item, ast.Import) and any(alias.name == "textwrap" for alias in item.names) for item in node.body):
            node.body.insert(1 if node.body and isinstance(node.body[0], ast.Expr) else 0, ast.Import([ast.alias("textwrap")]))
        return node

    def visit_Assign(self, node: ast.Assign):
        node = self.generic_visit(node)
        names = {target.id for target in node.targets if isinstance(target, ast.Name)}
        if names == {"ROOT"}:
            node.value = ast.Call(ast.Name("Path", ast.Load()), [ast.Constant(str(self.root))], [])
        elif names == {"output"}:
            node.value = ast.Call(ast.Name("Path", ast.Load()), [ast.Constant(str(self.output))], [])
        return node

    def visit_Dict(self, node: ast.Dict):
        node = self.generic_visit(node)
        for index, key in enumerate(node.keys):
            if isinstance(key, ast.Constant) and key.value in _FONT_KEYS:
                node.values[index] = self._font(node.values[index])
        return node

    def visit_Call(self, node: ast.Call):
        node = self.generic_visit(node)
        for argument in node.keywords:
            if argument.arg in {"fontsize", "labelsize"}:
                argument.value = self._font(argument.value)
        if isinstance(node.func, ast.Attribute):
            if isinstance(node.func.value, ast.Name) and node.func.value.id == "textwrap" and node.func.attr == "wrap" and len(node.args) >= 2:
                if self.template == "multitask_matrix" and isinstance(node.args[0], ast.Name) and node.args[0].id == "dataset":
                    node.args[1] = ast.Constant(15)
                elif self.template == "risk_coverage" and isinstance(node.args[0], ast.Name) and node.args[0].id == "dataset":
                    node.args[1] = ast.Constant(11)
                    node.keywords.extend([ast.keyword("break_long_words", ast.Constant(True)),
                                          ast.keyword("break_on_hyphens", ast.Constant(True))])
            if node.func.attr in {"set_xlabel", "set_ylabel"} and node.args:
                node.args[0] = ast.Call(ast.Attribute(ast.Name("textwrap", ast.Load()), "fill", ast.Load()),
                                       [node.args[0]], [ast.keyword("width", ast.Constant(44 if node.func.attr == "set_xlabel" else 28))])
            if node.func.attr == "subplots":
                if self.template == "risk_coverage" and len(node.args) >= 2:
                    node.args[0], node.args[1] = ast.Constant(2), ast.Constant(1)
                    for argument in node.keywords:
                        if argument.arg == "gridspec_kw" and isinstance(argument.value, ast.Dict):
                            for key in argument.value.keys:
                                if isinstance(key, ast.Constant) and key.value == "width_ratios":
                                    key.value = "height_ratios"
                self._grow_height(node)
            if self.template == "risk_coverage" and node.func.attr == "set_xticks":
                for argument in node.keywords:
                    if argument.arg == "rotation":
                        argument.value = ast.Constant(0)
                    elif argument.arg == "ha":
                        argument.value = ast.Constant("center")
        return node

    def visit_Constant(self, node: ast.Constant):
        # Current template line separators are presentation plumbing, not CSV
        # labels. Literal backslash-n must become an actual line break at print.
        return ast.Constant("\n") if node.value == "\\n" else node

    def _grow_height(self, node: ast.Call) -> None:
        for argument in node.keywords:
            if argument.arg != "figsize" or not isinstance(argument.value, ast.Tuple) or len(argument.value.elts) != 2:
                continue
            height = argument.value.elts[1]
            growth = max(1.25, self.multiplier) if self.template == "risk_coverage" else max(1.1, self.multiplier ** 0.5)
            if self.template == "risk_coverage" and len(node.args) >= 2:
                growth *= 2.0
            argument.value.elts[1] = ast.BinOp(height, ast.Mult(), ast.Constant(growth))

    def _font(self, value: ast.expr) -> ast.expr:
        if isinstance(value, ast.Constant) and isinstance(value.value, (int, float)):
            return ast.Constant(float(value.value) * self.multiplier)
        return value
