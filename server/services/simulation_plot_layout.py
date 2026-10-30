"""Wrap publication axis text without changing plotted values or scientific labels."""

from __future__ import annotations

import ast


class _AxisText(ast.NodeTransformer):
    def visit_Call(self, node: ast.Call) -> ast.AST:
        node = self.generic_visit(node)
        if not isinstance(node.func, ast.Attribute) or not node.args:
            return node
        widths = {"set_xlabel": 44, "set_ylabel": 28}
        width = widths.get(node.func.attr)
        if width is None:
            return node
        first = node.args[0]
        if (isinstance(first, ast.Call) and isinstance(first.func, ast.Attribute)
                and isinstance(first.func.value, ast.Name)
                and first.func.value.id == "textwrap" and first.func.attr == "fill"):
            return node
        node.args[0] = ast.Call(ast.Attribute(ast.Name("textwrap", ast.Load()), "fill", ast.Load()),
                               [first], [ast.keyword("width", ast.Constant(width))])
        return node


def wrap_plot_axis_text(source: str) -> str:
    """Project a trusted template to wrapped text; do not shorten or rename labels."""
    tree = _AxisText().visit(ast.parse(source))
    if not any(isinstance(item, ast.Import) and any(alias.name == "textwrap" for alias in item.names)
               for item in tree.body):
        index = 1 if tree.body and isinstance(tree.body[0], ast.Expr) else 0
        tree.body.insert(index, ast.Import([ast.alias("textwrap")]))
    return ast.unparse(ast.fix_missing_locations(tree)) + "\n"
