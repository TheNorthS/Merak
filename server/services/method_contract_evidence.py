"""Static source and configuration evidence parsing for method contracts."""

from __future__ import annotations

import ast
import configparser
import io
import json
import re
import tokenize
import tomllib
from functools import lru_cache
from pathlib import Path
from typing import Any


def _safe_json(path: Path) -> tuple[dict[str, Any], str]:
    if not path.is_file() or path.stat().st_size == 0:
        return {}, f"missing or empty contract: {path}"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return {}, f"invalid JSON contract {path}: {exc}"
    if not isinstance(payload, dict):
        return {}, f"contract root must be an object: {path}"
    return payload, ""


class PythonSymbolVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.symbols: set[str] = set()
        self.scope: list[str] = []
        self.scope_kinds: list[str] = []

    @classmethod
    def _target_names(cls, target: ast.AST) -> set[str]:
        if isinstance(target, ast.Name):
            return {target.id}
        if isinstance(target, (ast.Tuple, ast.List)):
            return set().union(*(cls._target_names(item) for item in target.elts))
        return set()

    @classmethod
    def _instance_attributes(cls, target: ast.AST) -> set[str]:
        if isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name):
            return {target.attr} if target.value.id in {"self", "cls"} else set()
        if isinstance(target, (ast.Tuple, ast.List)):
            return set().union(*(cls._instance_attributes(item) for item in target.elts))
        return set()

    def _class_prefix(self) -> str:
        return ".".join(
            name for name, kind in zip(self.scope, self.scope_kinds)
            if kind == "class"
        )

    def _visit_binding(self, targets: list[ast.AST]) -> None:
        if not self.scope:
            for target in targets:
                self.symbols.update(self._target_names(target))
            return
        prefix = self._class_prefix()
        if not prefix:
            return
        resolver = (
            self._target_names
            if self.scope_kinds[-1] == "class" else self._instance_attributes
        )
        for target in targets:
            self.symbols.update(f"{prefix}.{name}" for name in resolver(target))

    def _visit_named(self, node: ast.AST, name: str, kind: str) -> None:
        self.symbols.add(name)
        if self.scope:
            self.symbols.add(".".join([*self.scope, name]))
        self.scope.append(name)
        self.scope_kinds.append(kind)
        self.generic_visit(node)
        self.scope_kinds.pop()
        self.scope.pop()

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._visit_named(node, node.name, "class")

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_named(node, node.name, "function")

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_named(node, node.name, "function")

    def visit_Assign(self, node: ast.Assign) -> None:
        self._visit_binding(list(node.targets))
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        self._visit_binding([node.target])
        self.generic_visit(node)

    def visit_AugAssign(self, node: ast.AugAssign) -> None:
        self._visit_binding([node.target])
        self.generic_visit(node)

    def visit_Import(self, node: ast.Import) -> None:
        if not self.scope:
            self.symbols.update(item.asname or item.name.split(".", 1)[0] for item in node.names)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if not self.scope:
            self.symbols.update(item.asname or item.name for item in node.names if item.name != "*")


def _python_symbols(path: Path) -> tuple[set[str], str]:
    try:
        text = path.read_text(encoding="utf-8-sig")
        parse = _python_symbol_facts if len(text) <= 262_144 else _python_symbol_facts.__wrapped__
        return set(parse(text, str(path))), ""
    except (OSError, UnicodeError, SyntaxError) as exc:
        return set(), f"cannot parse Python evidence {path}: {exc}"


@lru_cache(maxsize=32)
def _python_symbol_facts(text: str, filename: str) -> frozenset[str]:
    """Cache immutable parse facts by complete current text, never file metadata or verdicts."""
    tree = ast.parse(text, filename=filename)
    visitor = PythonSymbolVisitor()
    visitor.visit(tree)
    return frozenset(visitor.symbols)



def _python_structured_data_keys(path: Path) -> tuple[set[str], str]:
    """Return exact mapping/batch/output keys used by executable Python code.

    Model writers sometimes put fields such as ``channel_presence_mask`` or
    output keys such as ``three_endpoint_payload`` in the ``symbols`` selector.
    They are not definitions, but they are still strong structural evidence
    when AST shows an exact subscript, ``.get`` call, or dictionary key.  Do
    not fall back to raw text: comments and prose must never satisfy a gate.
    """
    try:
        text = path.read_text(encoding="utf-8-sig")
        parse = _python_data_key_facts if len(text) <= 262_144 else _python_data_key_facts.__wrapped__
        return set(parse(text, str(path))), ""
    except (OSError, UnicodeError, SyntaxError) as exc:
        return set(), f"cannot parse Python evidence {path}: {exc}"


@lru_cache(maxsize=32)
def _python_data_key_facts(text: str, filename: str) -> frozenset[str]:
    """Repeated selectors share parsing only when the complete current source is identical."""
    tree = ast.parse(text, filename=filename)
    keys: set[str] = set()

    def string_value(node: ast.AST | None) -> str:
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value.strip()
        return ""

    class Visitor(ast.NodeVisitor):
        def visit_Dict(self, node: ast.Dict) -> None:  # noqa: N802
            for key in node.keys:
                value = string_value(key)
                if value:
                    keys.add(value)
            self.generic_visit(node)

        def visit_Subscript(self, node: ast.Subscript) -> None:  # noqa: N802
            value = string_value(node.slice)
            if value:
                keys.add(value)
            self.generic_visit(node)

        def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
            if (
                isinstance(node.func, ast.Attribute)
                and node.func.attr in {"get", "pop", "setdefault"}
                and node.args
            ):
                value = string_value(node.args[0])
                if value:
                    keys.add(value)
            self.generic_visit(node)

    Visitor().visit(tree)
    return frozenset(keys)


def _text_without_comments(path: Path) -> tuple[str, str]:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        return "", f"cannot read implementation evidence {path}: {exc}"
    if path.suffix.lower() == ".py":
        try:
            tokens = tokenize.generate_tokens(io.StringIO(text).readline)
            text = tokenize.untokenize(
                token for token in tokens if token.type != tokenize.COMMENT
            )
        except (tokenize.TokenError, IndentationError):
            pass
    else:
        text = re.sub(r"/\*.*?\*/", " ", text, flags=re.DOTALL)
        text = re.sub(r"(?m)^\s*(?://|#|%).*$", " ", text)
        text = re.sub(r"(?m)\s+//.*$", " ", text)
    return text, ""


def _flatten_keys(value: Any, prefix: str = "") -> set[str]:
    keys: set[str] = set()
    if isinstance(value, dict):
        for raw_key, child in value.items():
            key = str(raw_key)
            dotted = f"{prefix}.{key}" if prefix else key
            keys.add(dotted)
            keys.update(_flatten_keys(child, dotted))
    elif isinstance(value, list):
        for child in value:
            keys.update(_flatten_keys(child, prefix))
    return keys


def _yaml_keys(text: str) -> set[str]:
    """Extract mapping paths without requiring a YAML runtime dependency."""
    keys: set[str] = set()
    stack: list[tuple[int, str]] = []
    for raw_line in text.splitlines():
        line = raw_line.split("#", 1)[0].rstrip()
        if not line.strip() or line.lstrip().startswith("-"):
            continue
        match = re.match(r"^(\s*)([A-Za-z0-9_.-]+)\s*:", line)
        if not match:
            continue
        indent = len(match.group(1).replace("\t", "    "))
        key = match.group(2)
        while stack and stack[-1][0] >= indent:
            stack.pop()
        dotted = ".".join([item[1] for item in stack] + [key])
        keys.add(dotted)
        stack.append((indent, key))
    return keys


def _config_keys(path: Path) -> tuple[set[str], str]:
    try:
        text = path.read_text(encoding="utf-8")
        suffix = path.suffix.lower()
        if suffix == ".json":
            return _flatten_keys(json.loads(text)), ""
        if suffix == ".toml":
            return _flatten_keys(tomllib.loads(text)), ""
        if suffix in {".yaml", ".yml"}:
            try:
                import yaml
            except ImportError:
                return _yaml_keys(text), ""
            try:
                payload = yaml.safe_load(text)
            except yaml.YAMLError as exc:
                return set(), f"cannot parse structured config evidence {path}: {exc}"
            return _flatten_keys(payload), ""
        if suffix in {".ini", ".cfg"}:
            parser = configparser.ConfigParser()
            parser.read_string(text)
            keys = {
                f"{section}.{key}"
                for section in parser.sections()
                for key in parser[section]
            }
            return keys, ""
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError, tomllib.TOMLDecodeError, configparser.Error) as exc:
        return set(), f"cannot parse structured config evidence {path}: {exc}"
    return set(), f"config_keys are unsupported for {path.suffix or 'extensionless files'}: {path}"
