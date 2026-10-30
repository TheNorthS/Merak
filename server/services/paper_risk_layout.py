"""Separate calibration panels, full legends and observation keys at paper scale."""

import ast


class _RiskLayout(ast.NodeTransformer):
    def visit_Expr(self, node: ast.Expr):
        call = node.value
        if isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute) and isinstance(call.func.value, ast.Name):
            owner, action = call.func.value.id, call.func.attr
            if (owner, action) in {("ax", "legend"), ("fig", "text")}:
                return None
            if (owner, action) == ("fig", "tight_layout"):
                return ast.parse(_RISK_LAYOUT).body
        return self.generic_visit(node)


def project_risk_layout(tree: ast.Module, name: str) -> ast.Module:
    return _RiskLayout().visit(tree) if name == "risk_coverage" else tree


_RISK_LAYOUT = '''
_risk_font = float(plt.rcParams['font.size'])
_risk_width = fig.get_figwidth()
_risk_handles, _risk_labels = ax.get_legend_handles_labels()
_risk_columns = min(2, max(1, len(_risk_labels)))
_risk_wrap_width = max(14, int((_risk_width * 72 - 58) / _risk_columns / (_risk_font * 0.6)))
_risk_labels = [textwrap.fill(' '.join(label.split()), _risk_wrap_width, break_long_words=False, break_on_hyphens=False) for label in _risk_labels]
_risk_rows = (len(_risk_labels) + _risk_columns - 1) // _risk_columns
_risk_lines = sum(max((len(label.splitlines()) for label in _risk_labels[row::max(1, _risk_rows)]), default=1) for row in range(_risk_rows))
_risk_legend_inches = (_risk_lines * _risk_font * 1.45 + _risk_rows * 10 + 24) / 72
_risk_notes = []
if has_dataset:
    _risk_note_width = max(20, int((_risk_width * 72 - 36) / (_risk_font * 0.56)))
    _risk_notes = [textwrap.fill(str(index + 1) + '. ' + dataset + '; coverage=' + coverage, _risk_note_width) for index, (dataset, coverage) in enumerate(populations)]
_risk_note_inches = (sum(len(label.splitlines()) for label in _risk_notes) * _risk_font * 1.4 + 18) / 72 if _risk_notes else 0
_risk_panel_inches = max(2.7, _risk_font * 17 / 72)
_risk_gap_inches = max(0.8, _risk_font * 5 / 72)
_risk_total = _risk_note_inches + _risk_legend_inches + _risk_gap_inches + _risk_panel_inches + 0.5
if has_dataset:
    _risk_total += _risk_panel_inches + _risk_gap_inches
fig.set_figheight(_risk_total)
_risk_left = max(0.17, (_risk_font * 5.0 + 12) / (_risk_width * 72))
_risk_axes_width = 0.96 - _risk_left
ax.set_position([_risk_left, (_risk_note_inches + _risk_legend_inches + _risk_gap_inches) / _risk_total, _risk_axes_width, _risk_panel_inches / _risk_total])
ax.set_title(ax.get_title(), fontsize=_risk_font)
if has_dataset:
    task_ax.set_position([_risk_left, (_risk_note_inches + _risk_legend_inches + 2 * _risk_gap_inches + _risk_panel_inches) / _risk_total, _risk_axes_width, _risk_panel_inches / _risk_total])
    task_ax.set_title(task_ax.get_title(), fontsize=_risk_font)
    task_ax.set_xlabel(task_ax.get_xlabel(), fontsize=_risk_font)
fig.legend(_risk_handles, _risk_labels, frameon=False, ncol=_risk_columns, loc='lower center', bbox_to_anchor=(0.5, (_risk_note_inches + 0.08) / _risk_total), fontsize=_risk_font, columnspacing=1.0)
if _risk_notes:
    fig.text(0.04, 0.01, '\\n'.join(_risk_notes), fontsize=_risk_font, ha='left', va='bottom')
'''
