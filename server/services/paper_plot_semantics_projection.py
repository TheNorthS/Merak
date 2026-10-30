"""Source-bound paper-only axes and population grouping for trusted plots.

This adapter receives only an exact current packaged template AST. It preserves
every original value and interval, while correcting labels and ensuring that
observations from different datasets never imply one population's trajectory.
The scientific CSV and original program are always read-only.
"""

from __future__ import annotations

import ast
import csv
from pathlib import Path
from typing import Any

from .paper_derived_figure_binding import local_path
from .publication_labels import publication_metric_label


TEMPLATES = frozenset({"multitask_matrix", "risk_coverage"})


def synthetic_source(root: Path, parameters: dict[str, Any], rows: list[dict[str, str]]) -> bool:
    """Recognize the reserved simulation namespace or explicit generated row status."""
    source = local_path(root, str(parameters["data_path"]))
    return source.is_relative_to((root / "experiments/results/simulated").resolve()) or bool(
        rows and all(row.get("status") == "synthetic_preview" for row in rows))


def _rows(root: Path, parameters: dict[str, Any]) -> list[dict[str, str]]:
    path = local_path(root, str(parameters["data_path"]))
    if path.is_symlink() or path.stat().st_nlink > 1:
        raise ValueError("Paper semantic projection requires owned source CSV bytes")
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    if not rows:
        raise ValueError("Paper semantic projection requires nonempty source rows")
    if any(not str(row.get("method") or "").strip() for row in rows):
        raise ValueError("Paper semantic projection needs each row's declared method")
    datasets = [str(row.get("dataset") or "").strip() for row in rows]
    if any(datasets) and not all(datasets):
        raise ValueError("Paper semantic projection cannot mix named and unknown populations")
    return rows


def _metric(rows: list[dict[str, str]], parameters: dict[str, Any], template: str) -> str:
    declared = {str(row.get("metric") or "").strip() for row in rows}
    if len(declared) != 1:
        raise ValueError("Paper semantic projection cannot merge different declared metrics")
    value = next(iter(declared))
    if not value:
        value = str(parameters.get("metric") or parameters.get("y_label") or "").strip()
    if not value:
        raise ValueError("Paper semantic projection requires an explicit metric label")
    label = publication_metric_label(value)
    if template == "multitask_matrix":
        direction = str(parameters["metric_direction"])
        if direction not in {"maximize", "minimize"}:
            raise ValueError("Trusted plot requires its declared metric direction")
        directions = {str(row.get("metric_direction") or "").strip() for row in rows}
        if directions != {""} and directions != {direction}:
            raise ValueError("Trusted plot direction conflicts with its source CSV")
        source = publication_metric_label(parameters["metric"])
        normalize = lambda text: "".join(character for character in text.casefold() if character.isalnum())
        if normalize(source) != normalize(label):
            raise ValueError("Trusted plot axis conflicts with its declared CSV metric")
    return label


def requires_source_presentation_projection(root: Path, entry: dict[str, Any]) -> bool:
    """Select known semantic projections even when original print fonts pass.

An unknown renderer keeps its existing contract; it is not executed by this
probe. Recognized exact templates must have readable owned source rows.
"""
    if not str(entry.get("source_path") or "").strip():
        return False
    source = local_path(root, str(entry["source_path"]))
    if source.suffix.casefold() != ".py":
        return False
    from .paper_trusted_plot_source import match_trusted_plot

    try:
        name, parameters, _template = match_trusted_plot(source.read_text(encoding="utf-8-sig"))
    except (SyntaxError, ValueError):
        return False
    if name not in TEMPLATES:
        return False
    _metric(_rows(root, parameters), parameters, name)
    return True


def _statements(source: str) -> list[ast.stmt]:
    return ast.parse(source).body


def _call(node: ast.AST, owner: str, operation: str) -> bool:
    return (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name) and node.func.value.id == owner
            and node.func.attr == operation)


class _MatrixAxes(ast.NodeTransformer):
    def __init__(self, metric: str, direction: str):
        self.metric = metric + (" (higher is better)" if direction == "maximize" else " (lower is better)")

    def visit_Call(self, node: ast.Call):
        node = self.generic_visit(node)
        if _call(node, "fig", "supxlabel"):
            node.args[0] = ast.Constant("Method index (legend order)")
        elif _call(node, "fig", "supylabel"):
            node.args[0] = ast.Constant(self.metric)
        elif _call(node, "panel", "set_xticks"):
            node.args[0] = ast.parse("[methods.index(str(row['method'])) for row in selected]", mode="eval").body
            node.args[1] = ast.parse("[str(methods.index(str(row['method'])) + 1) for row in selected]", mode="eval").body
        elif _call(node, "panel", "errorbar"):
            node.args[0] = ast.parse("methods.index(str(row['method']))", mode="eval").body
            for keyword in node.keywords:
                if keyword.arg == "fmt":
                    keyword.value = ast.parse("_paper_markers[methods.index(str(row['method'])) % len(_paper_markers)]", mode="eval").body
                elif keyword.arg == "color":
                    keyword.value = ast.parse("_paper_colors[methods.index(str(row['method'])) % len(_paper_colors)]", mode="eval").body
        return node


def _matrix(tree: ast.Module, parameters: dict[str, Any], metric: str) -> ast.Module:
    tree = _MatrixAxes(metric, str(parameters["metric_direction"])).visit(tree)
    for node in ast.walk(tree):
        if _call(node, "plt", "subplots"):
            for keyword in node.keywords:
                if keyword.arg == "figsize" and isinstance(keyword.value, ast.Tuple):
                    keyword.value.elts[1] = ast.BinOp(keyword.value.elts[1], ast.Mult(), ast.Constant(1.5))
    tree.body.insert(0, ast.Assign([ast.Name("_paper_markers", ast.Store())], ast.parse("['o','s','^','D','v','P','X','*','<','>']", mode="eval").body))
    tree.body.insert(1, ast.Assign([ast.Name("_paper_colors", ast.Store())], ast.parse(repr(parameters["colors"]), mode="eval").body))
    for index, statement in enumerate(tree.body):
        if isinstance(statement, ast.Assign) and any(isinstance(target, ast.Tuple) and
                [item.id for item in target.elts if isinstance(item, ast.Name)] == ["handles", "labels"] for target in statement.targets):
            tree.body[index:index + 1] = _statements("""
handles = [plt.Line2D([], [], marker=_paper_markers[index % len(_paper_markers)], linestyle='none', color=_paper_colors[index % len(_paper_colors)], markerfacecolor='white', label=str(index + 1) + '. ' + method) for index, method in enumerate(methods)]
labels = [str(index + 1) + '. ' + method + (f' (rank={mean_ranks[method]})' if mean_ranks.get(method) else '') for index, method in enumerate(methods)]
""")
            break
    return tree


def _risk_loop(colors: list[str]) -> list[ast.stmt]:
    return _statements(f"""
for index, method in enumerate(methods):
    populations = list(dict.fromkeys(str(row.get('dataset') or '') for row in rows if row['method'] == method))
    for population in populations:
        selected = sorted([row for row in rows if row['method'] == method and str(row.get('dataset') or '') == population], key=lambda row: float(row['coverage']))
        coverage = [float(row['coverage']) for row in selected]
        intervals = [_paper_metric_interval(row, True) for row in selected]
        risk, low, high = ([interval[column] for interval in intervals] for column in range(3))
        color = {colors!r}[index % len({colors!r})]
        label = '\\n'.join(textwrap.wrap(method, 28, break_long_words=False, break_on_hyphens=False)) if population == populations[0] else '_nolegend_'
        ax.errorbar(coverage, risk, yerr=[[max(0.0, value-lo) for value, lo in zip(risk, low)], [max(0.0, hi-value) for value, hi in zip(risk, high)]], fmt=markers[index % len(markers)], linestyle=line_styles[index % len(line_styles)] if len(selected) > 1 else 'none', markersize=4.2, linewidth=1.5, capsize=2.2, color=color, markerfacecolor='white', markeredgewidth=0.9, label=label)
        if has_dataset:
            observation_keys = list(dict.fromkeys((str(row['dataset']), str(row['coverage'])) for row in rows))
            for row, x_value, y_value in zip(selected, coverage, risk):
                observation = observation_keys.index((str(row['dataset']), str(row['coverage']))) + 1
                ax.annotate(str(observation), (x_value, y_value), xytext=(6 if index % 2 == 0 else -6, 8 if index % 2 == 0 else -16), textcoords='offset points', fontsize=9, color=color)
        if len(selected) > 1:
            ax.fill_between(coverage, low, high, color=color, alpha=0.12, linewidth=0)
""")


def _risk_values(colors: list[str], metric: str) -> list[ast.stmt]:
    return _statements(f"""
if has_dataset:
    populations = list(dict.fromkeys((str(row['dataset']), str(row['coverage'])) for row in rows))
    bar_width = min(0.32, 0.72 / max(1, len(methods)))
    for index, method in enumerate(methods):
        selected = [row for row in rows if row['method'] == method]
        x = [populations.index((str(row['dataset']), str(row['coverage']))) + (index - (len(methods) - 1) / 2) * bar_width for row in selected]
        intervals = [_paper_metric_interval(row, {'risk' in metric.casefold()!r}) for row in selected]
        estimates, lows, highs = ([interval[column] for interval in intervals] for column in range(3))
        color = {colors!r}[index % len({colors!r})]
        task_ax.bar(x, estimates, width=bar_width, color=color, alpha=0.84, label=method)
        task_ax.errorbar(x, estimates, yerr=[[max(0.0, value-lo) for value, lo in zip(estimates, lows)], [max(0.0, hi-value) for value, hi in zip(estimates, highs)]], fmt='none', ecolor='#222222', elinewidth=0.75, capsize=1.8)
    task_ax.set_xticks(range(len(populations)), [str(index+1) for index in range(len(populations))])
    task_ax.set_xlabel('Dataset-coverage record (index below)')
    task_ax.set_ylabel({metric!r})
    task_ax.set_title('Declared metric by dataset and coverage', fontsize=9)
    task_ax.grid(axis='y', color='#D1D5DB', linewidth=0.4, alpha=0.6)
    observation_labels = [textwrap.fill(str(index+1) + '. ' + dataset + '; coverage=' + coverage, width=58) for index, (dataset, coverage) in enumerate(populations)]
    fig.text(0.04, 0.01, '\\n'.join(observation_labels), fontsize=9, ha='left', va='bottom')
""")


def _risk(tree: ast.Module, parameters: dict[str, Any]) -> ast.Module:
    metric = parameters["_paper_metric"]
    body = _statements(_INTERVAL_FAMILY)
    for statement in tree.body:
        if isinstance(statement, ast.For) and isinstance(statement.target, ast.Tuple) and any(
                isinstance(item, ast.Name) and item.id == "method" for item in statement.target.elts):
            body.extend(_risk_loop(parameters["colors"]))
        elif (isinstance(statement, ast.If) and isinstance(statement.test, ast.Name)
                and statement.test.id == "has_dataset" and any(
                    isinstance(item, ast.Assign) and any(isinstance(target, ast.Name) and target.id == "datasets"
                    for target in item.targets) for item in statement.body)):
            body.extend(_risk_values(parameters["colors"], metric))
        else:
            body.append(statement)
    tree.body = body
    for node in ast.walk(tree):
        if _call(node, "ax", "set_title"):
            prefix = "Generated " if parameters["_paper_synthetic"] else ""
            node.args[0] = ast.Constant(prefix + "dataset-coverage records (indexed below)")
        elif _call(node, "fig", "tight_layout"):
            node.keywords.append(ast.keyword("rect", ast.parse("(0.02, min(0.32, max(0.22, 0.028 * len(populations))) if has_dataset else 0.15, 0.98, 0.98)", mode="eval").body))
        elif _call(node, "ax", "legend"):
            node.keywords = [ast.keyword("frameon", ast.Constant(False)), ast.keyword("ncol", ast.Constant(2)),
                            ast.keyword("loc", ast.Constant("upper left")),
                            ast.keyword("bbox_to_anchor", ast.parse("(0.0, -0.25)", mode="eval").body),
                            ast.keyword("fontsize", ast.Constant(8.5))]
        elif _call(node, "ax", "set_xlim"):
            node.args = [ast.parse("min(float(row['coverage']) for row in rows) - 0.05", mode="eval").body,
                         ast.parse("max(float(row['coverage']) for row in rows) + 0.05", mode="eval").body]
    return tree


_INTERVAL_FAMILY = '''
def _paper_metric_interval(row, risk):
    import math
    risk_keys = ('risk', 'risk_ci_low', 'risk_ci_high')
    keys = risk_keys if risk and any(key in row for key in risk_keys) else ('value', 'ci_low', 'ci_high')
    values = tuple(number(row.get(key)) for key in keys)
    if any(value is None or not math.isfinite(value) for value in values):
        raise ValueError('Calibration estimate requires one complete finite interval family: ' + ', '.join(keys))
    if not values[1] <= values[0] <= values[2]:
        raise ValueError('Calibration interval does not contain its estimate')
    return values
'''


def project_plot_semantics(tree: ast.Module, name: str, parameters: dict[str, Any], root: Path) -> ast.Module:
    """Transform only declared trusted presentation operations, not estimates."""
    if name not in TEMPLATES:
        return tree
    rows = _rows(root, parameters)
    metric = _metric(rows, parameters, name)
    if name == "multitask_matrix":
        return _matrix(tree, parameters, metric)
    return _risk(tree, {**parameters, "_paper_metric": metric,
                        "_paper_synthetic": synthetic_source(root, parameters, rows)})
