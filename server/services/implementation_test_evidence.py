"""Resolve supporting test classes/helpers without granting scientific execution evidence."""

import ast
from pathlib import Path

from .implementation_scopes import executable_scope_nodes


def is_test_file(path: Path) -> bool:
    return path.name.startswith('test_') or 'tests' in path.parts


def supporting_definitions(definitions: dict[str, ast.AST]) -> set[int]:
    """Only assertion-bearing tests and their explicitly called local helpers qualify."""
    def assertion(node):
        return any(isinstance(item, ast.Assert) or (
            isinstance(item, ast.Call) and isinstance(item.func, ast.Attribute)
            and isinstance(item.func.value, ast.Name) and item.func.value.id == 'self'
            and item.func.attr.startswith('assert')) for item in executable_scope_nodes(node))

    tests = [node for node in definitions.values()
             if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
             and node.name.startswith('test_') and assertion(node)]
    reached, pending = set(), list(tests)
    for node in definitions.values():
        if isinstance(node, ast.ClassDef) and any(id(child) in {id(test) for test in tests} for child in node.body):
            reached.add(id(node))
            pending.extend(child for child in node.body if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
                           and child.name in {'setUp', 'setUpClass', 'tearDown', 'tearDownClass'})
    while pending:
        node = pending.pop()
        if id(node) in reached:
            continue
        reached.add(id(node))
        for item in executable_scope_nodes(node):
            if not isinstance(item, ast.Call):
                continue
            name = item.func.id if isinstance(item.func, ast.Name) else (
                item.func.attr if isinstance(item.func, ast.Attribute)
                and isinstance(item.func.value, ast.Name) and item.func.value.id in {'self', 'cls'} else '')
            target = definitions.get(name)
            if isinstance(target, (ast.FunctionDef, ast.AsyncFunctionDef)):
                pending.append(target)
    return reached
