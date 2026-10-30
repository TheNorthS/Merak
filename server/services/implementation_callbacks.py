"""Recognize explicit callback positions, without treating printed names as calls."""
from __future__ import annotations

import ast
from collections.abc import Iterable


def callback_names(nodes: Iterable[ast.AST]) -> set[str]:
    names: set[str] = set()
    for node in nodes:
        if not isinstance(node, ast.Call):
            continue
        called = ast.unparse(node.func).rsplit(".", 1)[-1]
        arguments = []
        if called in {"map", "filter"}:
            arguments.extend(node.args[:1])
        keywords = {"key"} if called in {"sorted", "sort", "min", "max"} else set()
        if called == "DataLoader":
            keywords |= {"collate_fn", "worker_init_fn"}
        arguments.extend(item.value for item in node.keywords if item.arg in keywords)
        names.update(ast.unparse(item) for item in arguments
                     if isinstance(item, (ast.Name, ast.Attribute)))
    return names
