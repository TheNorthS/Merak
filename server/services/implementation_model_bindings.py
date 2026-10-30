"""Recognize calls on source-bound model instances, independent of variable spelling.

Only reached scopes and local class definitions contribute evidence. An annotation
or constructor alone is insufficient: an actual forward invocation is required.
This is static evidence, not a claim that arbitrary Python has been executed.
"""
from __future__ import annotations

import ast
from pathlib import Path

from .implementation_scopes import _active_scopes


def _type_name(value: ast.AST | None) -> str:
    if isinstance(value, ast.Constant) and isinstance(value.value, str):
        return value.value
    return ast.unparse(value) if isinstance(value, (ast.Name, ast.Attribute)) else ""


def _constructor(value: ast.AST | None) -> str:
    while isinstance(value, ast.Call):
        function = value.func
        if isinstance(function, ast.Attribute) and function.attr in {"to", "cpu", "cuda", "eval", "train"}:
            value = function.value
        else:
            return _type_name(function)
    return ""


def _instance_types(scope: ast.AST, nodes: list[ast.AST]) -> dict[str, str]:
    bindings: dict[str, set[str]] = {}
    if isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef)):
        for arg in [*scope.args.posonlyargs, *scope.args.args, *scope.args.kwonlyargs]:
            if arg.annotation:
                bindings.setdefault(arg.arg, set()).add(_type_name(arg.annotation))
    for node in nodes:
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            declared = _type_name(node.annotation) if isinstance(node, ast.AnnAssign) else ""
            type_name = _constructor(node.value) or declared
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, (ast.Name, ast.Attribute)):
                    bindings.setdefault(ast.unparse(target), set()).add(type_name)
    return {name: next(iter(types)) for name, types in bindings.items()
            if len(types) == 1 and "" not in types}


def has_bound_model_forward(trees: dict[Path, ast.Module], reached: list[ast.AST]) -> bool:
    from .implementation_graph import _imports_for, _import_bindings, _module_index, definition_nodes

    modules = _module_index(trees)
    owners = {id(node): path for path, tree in trees.items() for node in ast.walk(tree)}
    definitions = {path: definition_nodes(tree) for path, tree in trees.items()}
    for root in reached:
        path = owners.get(id(root))
        if path is None:
            continue
        imports = _imports_for(path, trees, modules)
        for scope, nodes in _active_scopes(root):
            aliases = {**imports, **_import_bindings(path, nodes, trees, modules)}
            instances = _instance_types(scope, nodes)
            for node in nodes:
                if not isinstance(node, ast.Call):
                    continue
                receiver = node.func.value if isinstance(node.func, ast.Attribute) else node.func
                type_name = instances.get(_type_name(receiver), "")
                if not type_name:
                    continue
                target, symbol = aliases.get(type_name, (path, type_name))
                cls = definitions.get(target, {}).get(symbol)
                if not isinstance(cls, ast.ClassDef):
                    continue
                methods = {child.name for child in cls.body if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))}
                method = node.func.attr if isinstance(node.func, ast.Attribute) else "forward"
                if method in methods and (method == "forward" or method.startswith("forward_")):
                    return True
    return False
