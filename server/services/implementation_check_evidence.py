"""Separate static test evidence from scientific runtime reachability."""
from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

from .implementation_scopes import executable_scope_nodes


def is_test_symbol(path: Path, symbol: str) -> bool:
    return (path.name.startswith("test_") or "tests" in path.parts) and symbol.rsplit(".", 1)[-1].startswith("test_")


def _has_assertion(node: ast.AST) -> bool:
    return any(isinstance(item, ast.Assert) or (
        isinstance(item, ast.Call) and isinstance(item.func, ast.Attribute)
        and isinstance(item.func.value, ast.Name) and item.func.value.id == "self"
        and item.func.attr.startswith("assert")
    ) for item in executable_scope_nodes(node))


def check_coverage(service: Any, symbols: list[tuple[Path, str]], context: dict) -> dict:
    from .implementation_test_evidence import is_test_file, supporting_definitions
    supporting = bool(symbols) and all(is_test_file(path) for path, _ in symbols)
    substantive, invoked, required, tests = [], [], [], []
    test_reached = {path: supporting_definitions(context['definitions'].get(path, {}))
                    for path, _ in symbols if is_test_file(path)}
    for path, symbol in symbols:
        simple = symbol.rsplit(".", 1)[-1]
        definitions = context["definitions"].get(path, {})
        qualified = symbol.removeprefix(path.stem + ".")
        node = definitions.get(qualified) or definitions.get(symbol) or definitions.get(simple)
        if node is None and is_test_file(path):
            candidates = {id(value): value for key, value in definitions.items() if key.endswith('.' + simple)}
            node = next(iter(candidates.values())) if len(candidates) == 1 else None
        if node is not None and service._definition_is_substantive(node):
            substantive.append(symbol)
        if is_test_file(path):
            required.append(symbol)
            if node is not None and id(node) in test_reached[path]:
                invoked.append(symbol)
                tests.append(symbol)
        elif not service._STATIC_SYMBOL.match(simple):
            required.append(symbol)
            if node is not None and id(node) in context["reached_definition_ids"]:
                invoked.append(symbol)
    missing = sorted(set(required) - (set(invoked) & set(substantive)))
    return {"declared_symbols": [symbol for _, symbol in symbols],
            "substantive_symbols": substantive, "reachable_symbols": [symbol for symbol in invoked if symbol not in tests],
            "supporting_test_symbols": tests,
            "evidence_kind": "supporting_test_static" if supporting else "runtime_static",
            "execution_verified": False, "required_symbols": required,
            "missing_symbols": missing, "passed": bool(required and not missing)}
