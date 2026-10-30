"""Resolve imports only inside genuinely reached Python lexical scopes.

Assignments/parameters that shadow an import fail closed for that whole scope;
the static auditor does not execute guards or guess a runtime branch/order.
Uncalled nested imports never become a module or sibling's evidence.
"""

from __future__ import annotations

import ast
from collections.abc import Callable, Iterator
from pathlib import Path

from .implementation_scopes import _active_scopes
from .implementation_callbacks import callback_names


ImportMap = dict[str, tuple[Path, str | None]]
_SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)


def _scope_nodes(node: ast.AST) -> Iterator[ast.AST]:
    yield node
    for child in ast.iter_child_nodes(node):
        if isinstance(child, _SCOPES):
            yield child
        else:
            yield from _scope_nodes(child)


def _bound_names(scope: ast.AST, nodes: list[ast.AST]) -> tuple[set[str], set[str]]:
    imports, shadowed = set(), set()
    if isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
        arguments = [*scope.args.posonlyargs, *scope.args.args, *scope.args.kwonlyargs]
        arguments.extend(item for item in (scope.args.vararg, scope.args.kwarg) if item)
        shadowed.update(item.arg for item in arguments)
    for node in nodes:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            imports.update(item.asname or item.name for item in node.names if item.name != "*")
        elif isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
            shadowed.add(node.id)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node is not scope:
            shadowed.add(node.name)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            shadowed.add(node.name)
    return imports, shadowed


def _parents(root: ast.AST) -> dict[int, ast.AST]:
    parents = {}

    def visit(node: ast.AST, enclosing: ast.AST) -> None:
        if node is not root and isinstance(node, _SCOPES):
            parents[id(node)] = enclosing
            enclosing = node
        for child in ast.iter_child_nodes(node):
            visit(child, enclosing)

    visit(root, root)
    return parents


def lexical_call_bindings(
    node: ast.AST, module_imports: ImportMap,
    resolve_imports: Callable[[list[ast.AST]], ImportMap],
) -> Iterator[tuple[set[str], ImportMap, set[str]]]:
    """Keep call sites attached to their own function/closure import environment."""
    parents, cache = _parents(node), {}

    def environment(scope: ast.AST) -> tuple[ImportMap, set[str]]:
        if id(scope) in cache:
            return cache[id(scope)]
        parent = parents.get(id(scope))
        # Python methods do not lexically inherit class-body bare names.
        inherited, inherited_blocks = environment(parent) if parent is not None and not isinstance(parent, ast.ClassDef) else (module_imports, set())
        nodes = list(_scope_nodes(scope))
        declared, shadowed = _bound_names(scope, nodes)
        aliases = {name: value for name, value in inherited.items()
                   if name.split(".", 1)[0] not in declared | shadowed and name not in declared | shadowed}
        local = {name: value for name, value in resolve_imports(nodes).items()
                 if name.split(".", 1)[0] not in shadowed}
        aliases.update(local)
        blocked = (inherited_blocks - set(local)) | shadowed | (declared - set(aliases))
        cache[id(scope)] = aliases, blocked
        return aliases, blocked

    for scope, nodes in _active_scopes(node):
        aliases, blocked = environment(scope)
        calls = {ast.unparse(item.func) for item in nodes if isinstance(item, ast.Call)
                 and isinstance(item.func, (ast.Name, ast.Attribute))}
        calls.update(callback_names(nodes))
        yield calls, aliases, blocked
