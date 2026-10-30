"""Paper-only placement for long curve legends without changing source observations."""

import ast


def project_curve_legend(tree: ast.Module, name: str) -> ast.Module:
    """Reserve measured rows below a trusted single-axis curve; preserve all labels."""
    if name != "robustness":
        return tree
    body = []
    for statement in tree.body:
        call = statement.value if isinstance(statement, ast.Expr) else None
        if (isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
                and isinstance(call.func.value, ast.Name)):
            if call.func.value.id == "ax" and call.func.attr == "legend":
                continue
            if call.func.value.id == "fig" and call.func.attr == "tight_layout":
                body.extend(ast.parse(_CURVE_LEGEND).body)
                continue
        body.append(statement)
    tree.body = body
    return tree


_CURVE_LEGEND = '''
_curve_handles, _curve_labels = ax.get_legend_handles_labels()
_curve_font = float(plt.rcParams['font.size'])
_curve_columns = min(2, max(1, len(_curve_labels)))
_curve_width = max(14, int((fig.get_figwidth() * 72 - 42) / _curve_columns / (_curve_font * 0.6)))
_curve_wrapped = [textwrap.fill(label, width=_curve_width, break_long_words=False, break_on_hyphens=False) for label in _curve_labels]
_curve_rows = (len(_curve_wrapped) + _curve_columns - 1) // _curve_columns
_curve_lines = sum(max((len(label.splitlines()) for label in _curve_wrapped[row::max(1, _curve_rows)]), default=1) for row in range(_curve_rows))
_curve_legend_height = (_curve_lines * _curve_font * 1.5 + _curve_rows * 10 + 26) / 72
_curve_plot_height = fig.get_figheight()
fig.set_figheight(_curve_plot_height + _curve_legend_height)
fig.legend(_curve_handles, _curve_wrapped, frameon=False, ncol=_curve_columns, loc='lower center', bbox_to_anchor=(0.5, 0.01), handlelength=2.0, columnspacing=1.0)
fig.tight_layout(rect=(0.02, _curve_legend_height / fig.get_figheight(), 0.98, 0.98), pad=0.8)
'''
