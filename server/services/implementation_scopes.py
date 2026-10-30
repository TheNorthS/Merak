"""Project static evidence onto invoked lexical scopes without executing code.

Reached framework classes retain callback inspection. A nested function or
lambda contributes evidence only when called or passed as a call argument.
Projections are diagnostic text, never executable source or artifact rewrites.
"""

from __future__ import annotations

import ast
import copy
from collections.abc import Iterator


_SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)


def _lexical_nodes(node: ast.AST) -> Iterator[ast.AST]:
    yield node
    for child in ast.iter_child_nodes(node):
        if isinstance(child, _SCOPES):
            yield child
        else:
            yield from _lexical_nodes(child)


def _local_bindings(nodes: list[ast.AST]) -> dict[str, list[ast.AST]]:
    bindings: dict[str, list[ast.AST]] = {}
    for node in nodes[1:]:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            bindings.setdefault(node.name, []).append(node)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            if isinstance(node.value, ast.Lambda):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                for target in targets:
                    if isinstance(target, ast.Name):
                        bindings.setdefault(target.id, []).append(node.value)
    return bindings


def _invoked_bindings(nodes: list[ast.AST]) -> tuple[set[str], list[ast.AST]]:
    names: set[str] = set()
    immediate: list[ast.AST] = []
    for node in nodes:
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name):
            names.add(node.func.id)
        elif isinstance(node.func, ast.Lambda):
            immediate.append(node.func)
        # A local callback passed to another operation may be invoked there;
        # mere assignment/reference does not make its body reachable.
        for argument in [*node.args, *[keyword.value for keyword in node.keywords]]:
            if isinstance(argument, ast.Name):
                names.add(argument.id)
            elif isinstance(argument, ast.Lambda):
                immediate.append(argument)
    return names, immediate


def _active_scopes(node: ast.AST) -> Iterator[tuple[ast.AST, list[ast.AST]]]:
    pending: list[tuple[ast.AST, dict[str, list[ast.AST]]]] = [(node, {})]
    visited: set[int] = set()
    while pending:
        scope, inherited = pending.pop()
        if id(scope) in visited:
            continue
        visited.add(id(scope))
        nodes = list(_lexical_nodes(scope))
        bindings = {**inherited, **_local_bindings(nodes)}
        invoked, immediate = _invoked_bindings(nodes)
        if isinstance(scope, ast.ClassDef):
            immediate.extend(
                child for child in scope.body
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
            )
        callees = immediate + [child for name in invoked for child in bindings.get(name, [])]
        pending.extend((child, bindings) for child in callees)
        yield scope, nodes


def executable_scope_nodes(node: ast.AST) -> Iterator[ast.AST]:
    """Inspect reached callbacks and invoked helpers, excluding dead bodies."""
    for _, nodes in _active_scopes(node):
        yield from nodes


class _NestedScopePruner(ast.NodeTransformer):
    """Remove nested body evidence from a copied single-scope projection."""

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        return None

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        return None

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        return None

    def visit_Import(self, node: ast.Import) -> None:
        return None

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        return None

    def visit_Lambda(self, node: ast.Lambda) -> ast.Constant:
        return ast.copy_location(ast.Constant(value=None), node)

    def visit_Assign(self, node: ast.Assign) -> ast.AST | None:
        return None if isinstance(node.value, ast.Lambda) else self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> ast.AST | None:
        return None if isinstance(node.value, ast.Lambda) else self.generic_visit(node)


def reachable_nodes_source(nodes: list[ast.AST]) -> str:
    """Render only active lexical bodies; never mutate the caller's ASTs."""
    parts: list[str] = []
    visited: set[int] = set()
    for node in nodes:
        for scope, _ in _active_scopes(node):
            if id(scope) in visited:
                continue
            visited.add(id(scope))
            projection = _NestedScopePruner().generic_visit(copy.deepcopy(scope))
            for statement in ast.walk(projection):
                if hasattr(statement, "body") and statement.body == []:
                    statement.body = [ast.Pass()]
            try:
                parts.append(ast.unparse(projection))
            except (AttributeError, TypeError, ValueError, RecursionError):
                continue
    return "\n".join(parts)
