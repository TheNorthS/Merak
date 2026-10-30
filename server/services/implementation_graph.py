"""Static call-graph discovery without importing generated experiment code.

Imports belong to their lexical scope: module-level guards are transparent,
whereas imports inside an uncalled function or class cannot bind the module.
"""

from __future__ import annotations

import ast
from collections.abc import Iterator
from pathlib import Path

from .implementation_scopes import executable_scope_nodes, reachable_nodes_source
from .implementation_import_scopes import lexical_call_bindings
from .implementation_callbacks import callback_names


def definition_nodes(tree: ast.Module) -> dict[str, ast.AST]:
    definitions: dict[str, ast.AST] = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            definitions[node.name] = node
            if isinstance(node, ast.ClassDef):
                for child in node.body:
                    if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        definitions[f"{node.name}.{child.name}"] = child
    return definitions


def call_names(node: ast.AST) -> set[str]:
    calls: set[str] = set()
    for child in executable_scope_nodes(node):
        if not isinstance(child, ast.Call):
            continue
        if isinstance(child.func, ast.Name):
            calls.add(child.func.id)
        elif isinstance(child.func, ast.Attribute):
            calls.add(child.func.attr)
            try:
                calls.add(ast.unparse(child.func))
            except (AttributeError, TypeError, ValueError, RecursionError):
                continue
    calls.update(callback_names(executable_scope_nodes(node)))
    return calls


def _imports_for(
    path: Path,
    trees: dict[Path, ast.Module],
    module_by_name: dict[str, Path],
) -> dict[str, tuple[Path, str | None]]:
    tree = trees.get(path)
    if tree is None:
        return {}
    return _import_bindings(path, list(_module_scope_nodes(tree)), trees, module_by_name)


def _import_bindings(
    path: Path, nodes: list[ast.AST], trees: dict[Path, ast.Module], module_by_name: dict[str, Path],
) -> dict[str, tuple[Path, str | None]]:
    candidates: dict[str, set[tuple[Path, str | None] | None]] = {}
    for node in nodes:
        if isinstance(node, ast.Import):
            for item in node.names:
                target = _import_target(path, item.name, 0, trees, module_by_name)
                binding = item.asname or item.name
                candidates.setdefault(binding, set()).add((target, None) if target else None)
        elif isinstance(node, ast.ImportFrom):
            target = _import_target(path, node.module or "", node.level, trees, module_by_name)
            for item in node.names:
                if item.name != "*":
                    binding = item.asname or item.name
                    value = _from_import_value(path, node, item, target, trees, module_by_name)
                    candidates.setdefault(binding, set()).add(value)
    # Equivalent absolute/relative fallback imports agree. Conflicting guards
    # cannot justify choosing an arbitrary local implementation as evidence.
    return {
        alias: next(iter(values))
        for alias, values in candidates.items()
        if len(values) == 1 and None not in values
    }


def _from_import_value(
    path: Path,
    node: ast.ImportFrom,
    item: ast.alias,
    target: Path | None,
    trees: dict[Path, ast.Module],
    module_by_name: dict[str, Path],
) -> tuple[Path, str | None] | None:
    if target is not None and item.name in definition_nodes(trees[target]):
        return target, item.name
    child_module = ".".join(filter(None, (node.module, item.name)))
    child_target = _import_target(path, child_module, node.level, trees, module_by_name)
    if child_target is not None:
        return child_target, None
    return (target, item.name) if target is not None else None


def _module_scope_nodes(node: ast.AST) -> Iterator[ast.AST]:
    """Visit guarded module statements, never a nested Python scope."""
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            continue
        yield child
        yield from _module_scope_nodes(child)


def _import_target(
    source: Path,
    module: str,
    level: int,
    trees: dict[Path, ast.Module],
    module_by_name: dict[str, Path],
) -> Path | None:
    parts = module.split(".") if module else []
    bases = [source.parent]
    if level:
        for _ in range(level - 1):
            bases[0] = bases[0].parent
    else:
        bases.extend(source.parents[1:])
    for base in bases:
        target = base.joinpath(*parts)
        for candidate in (target.with_suffix(".py"), target / "__init__.py"):
            if candidate in trees:
                return candidate
    if not level:
        return module_by_name.get(module)
    return None


def _module_index(trees: dict[Path, ast.Module]) -> dict[str, Path]:
    candidates: dict[str, set[Path]] = {}
    for path in trees:
        parts = path.with_suffix("").parts
        if parts[-1] == "__init__":
            parts = parts[:-1]
        for start in range(len(parts)):
            candidates.setdefault(".".join(parts[start:]), set()).add(path)
    return {
        name: next(iter(paths)) for name, paths in candidates.items()
        if len(paths) == 1
    }


def _imported_call(
    called: str, aliases: dict[str, tuple[Path, str | None]],
) -> tuple[Path, str] | None:
    matches = [
        alias for alias in aliases
        if called == alias or called.startswith(f"{alias}.")
    ]
    if not matches:
        return None
    target, imported = aliases[max(matches, key=len)]
    return target, imported or called.rsplit(".", 1)[-1]


def _entrypoint_roots(
    entrypoint: Path | None,
    tree: ast.Module | None,
    definitions: dict[str, ast.AST],
) -> tuple[list[str], list[ast.AST]]:
    # Prefer the declared module's conventional entry, never seed uncalled
    # train/run helpers alongside main; that would make dead code evidence.
    queue = next(([name] for name in ("main", "run", "train", "execute") if name in definitions), [])
    is_test = bool(entrypoint and (
        entrypoint.name.casefold().startswith("test_")
        or "tests" in {part.casefold() for part in entrypoint.parts}
    ))
    if is_test:
        queue.extend(
            name for name in definitions
            if name.rsplit(".", 1)[-1].casefold().startswith("test_")
            and name not in queue
        )
    statements = [] if tree is None else [
        node for node in tree.body
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    ]
    roots = [ast.Module(body=statements, type_ignores=[])] if statements else []
    return queue, roots


def reachable_graph(
    trees: dict[Path, ast.Module],
    entrypoint: Path | None,
) -> tuple[set[str], list[ast.AST]]:
    definitions = {path: definition_nodes(tree) for path, tree in trees.items()}
    module_by_name = _module_index(trees)
    imports = {path: _imports_for(path, trees, module_by_name) for path in trees}
    entry_tree = trees.get(entrypoint) if entrypoint is not None else None
    entry_definitions = definitions.get(entrypoint, {}) if entry_tree is not None else {}
    queue, root_nodes = _entrypoint_roots(entrypoint, entry_tree, entry_definitions)
    queue_nodes = [(entrypoint, name) for name in queue] if entrypoint else []
    for root_node in root_nodes:
        for called in call_names(root_node):
            simple = called.rsplit(".", 1)[-1]
            if entrypoint is not None and simple in entry_definitions:
                queue_nodes.append((entrypoint, simple))
            elif entrypoint is not None:
                alias = _imported_call(called, imports.get(entrypoint, {}))
                if alias:
                    queue_nodes.append(alias)
    if not queue and not root_nodes:
        return set(), []
    reached: set[tuple[Path, str]] = set()
    calls: set[str] = set()
    reached_nodes: list[ast.AST] = list(root_nodes)
    while queue_nodes:
        module_path, name = queue_nodes.pop(0)
        module_definitions = definitions.get(module_path, {})
        node = module_definitions.get(name) or module_definitions.get(name.rsplit(".", 1)[-1])
        if node is None or (module_path, name) in reached:
            continue
        reached.add((module_path, name))
        reached_nodes.append(node)
        local_calls = call_names(node)
        calls.update(local_calls)
        resolver = lambda scoped_nodes: _import_bindings(module_path, scoped_nodes, trees, module_by_name)
        for scoped_calls, aliases, blocked in lexical_call_bindings(node, imports.get(module_path, {}), resolver):
            for called in scoped_calls:
                if called.split(".", 1)[0] in blocked:
                    continue
                if called in module_definitions and called not in aliases:
                    queue_nodes.append((module_path, called))
                else:
                    alias = _imported_call(called, aliases)
                    if alias:
                        queue_nodes.append(alias)
    reachable_names = set(calls)
    reachable_names.update(name for _, name in reached)
    return reachable_names, reached_nodes
