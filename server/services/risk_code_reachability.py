"""Inspect reachable Python scaffolds without importing research dependencies."""

from __future__ import annotations

import ast
import re
from pathlib import Path


def _function_calls_and_placeholders(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
) -> tuple[set[str], list[str]]:
    direct_calls: set[str] = set()
    reasons: list[str] = []
    body = list(function.body)
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        body = body[1:]
    if body and all(
        (
            isinstance(node, ast.Pass)
            or (
                isinstance(node, ast.Expr)
                and isinstance(node.value, ast.Constant)
                and (node.value.value is Ellipsis)
            )
            for node in body
        )
    ):
        reasons.append("function body is only pass/ellipsis")
    for node in ast.walk(function):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                direct_calls.add(node.func.id)
            elif isinstance(node.func, ast.Attribute):
                direct_calls.add(node.func.attr)
        if not isinstance(node, ast.Raise) or node.exc is None:
            continue
        raised = node.exc.func if isinstance(node.exc, ast.Call) else node.exc
        if isinstance(raised, ast.Name) and raised.id == "NotImplementedError":
            reasons.append("raises NotImplementedError")
        if isinstance(raised, ast.Name) and raised.id in {"RuntimeError", "ValueError"}:
            message = ""
            if isinstance(node.exc, ast.Call) and node.exc.args:
                first_arg = node.exc.args[0]
                if isinstance(first_arg, ast.Constant) and isinstance(
                    first_arg.value, str
                ):
                    message = first_arg.value.casefold()
            if re.search(
                "(?:not\\s+implemented|no\\s+scientific\\s+training|scaffold.*(?:preflight|training)|preflight.*only)",
                message,
            ):
                reasons.append("raises an explicit scaffold/no-training error")
    return (direct_calls, sorted(set(reasons)))


def reachable_python_placeholders(path: Path) -> list[str]:
    """Return explicit placeholders reachable from a conventional script entrypoint."""
    try:
        tree = ast.parse(
            path.read_text(encoding="utf-8-sig", errors="strict"), filename=str(path)
        )
    except (OSError, UnicodeError, SyntaxError):
        return []
    functions = {
        node.name: node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    if not functions:
        return []
    calls: dict[str, set[str]] = {}
    blockers: dict[str, list[str]] = {}
    for name, function in functions.items():
        direct_calls, reasons = _function_calls_and_placeholders(function)
        calls[name] = direct_calls
        if reasons:
            blockers[name] = reasons
    entrypoints = {"main"} if "main" in functions else set()
    if not entrypoints:
        module_calls = {
            node.func.id
            for node in tree.body
            for node in ast.walk(node)
            if not isinstance(
                node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
            )
            and isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and (node.func.id in functions)
        }
        entrypoints.update(module_calls)
    if not entrypoints:
        return []
    reachable: set[str] = set()
    pending = list(entrypoints)
    while pending:
        name = pending.pop()
        if name in reachable or name not in functions:
            continue
        reachable.add(name)
        pending.extend(calls.get(name, set()) - reachable)
    return [
        f"{name}: {reason}"
        for name in sorted(reachable)
        for reason in blockers.get(name, [])
    ]
