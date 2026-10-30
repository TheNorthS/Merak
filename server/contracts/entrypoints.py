"""Canonical parsing and verification for project-local Python entrypoints."""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any


_SYMBOL = re.compile(r"^[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*$")


@dataclass(frozen=True)
class PythonEntrypointRef:
    """One Python source path and optional dotted callable symbol."""

    path: PurePosixPath
    symbol: str = ""

    @property
    def serialized(self) -> str:
        return f"{self.path.as_posix()}:{self.symbol}" if self.symbol else self.path.as_posix()

    def resolve(self, project_root: str | Path) -> Path:
        root = Path(project_root).expanduser().resolve()
        candidate = (root / Path(self.path.as_posix())).resolve()
        try:
            candidate.relative_to(root)
        except ValueError as error:
            raise ValueError(f"entrypoint escapes project: {self.serialized}") from error
        return candidate

    def validation_issues(self, project_root: str | Path) -> list[str]:
        source = self.resolve(project_root)
        if not source.is_file() or source.stat().st_size == 0:
            return [f"entrypoint source is missing or empty: {self.path.as_posix()}"]
        try:
            tree = ast.parse(source.read_text(encoding="utf-8-sig"), filename=str(source))
        except (OSError, UnicodeError, SyntaxError) as error:
            return [f"entrypoint source is not valid Python: {error}"]
        if not self.symbol:
            return []
        definitions = _definition_paths(tree)
        return [] if self.symbol in definitions else [
            f"entrypoint symbol is absent: {self.serialized}"
        ]


def _definition_paths(tree: ast.Module) -> set[str]:
    found: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            found.add(node.name)
            if isinstance(node, ast.ClassDef):
                found.update(
                    f"{node.name}.{child.name}"
                    for child in node.body
                    if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
                )
    return found


def parse_python_entrypoint(value: Any) -> PythonEntrypointRef:
    """Parse the one current entrypoint form: project `.py` path plus symbol."""
    if isinstance(value, dict):
        raw_path = str(value.get("path") or "").strip()
        symbol = str(value.get("symbol") or "").strip()
    else:
        raw = str(value or "").strip().replace("\\", "/")
        raw_path, symbol = raw, ""
        if ".py:" in raw.casefold():
            marker = raw.casefold().rfind(".py:") + 3
            raw_path, symbol = raw[:marker], raw[marker + 1 :]
    if not raw_path:
        raise ValueError("entrypoint path is required")
    path = PurePosixPath(raw_path.replace("\\", "/"))
    windows_absolute = bool(re.match(r"^[A-Za-z]:/", raw_path.replace("\\", "/")))
    if windows_absolute or path.is_absolute() or ".." in path.parts or path.suffix.casefold() != ".py":
        raise ValueError(f"entrypoint must be a project-local .py path: {raw_path}")
    if symbol and not _SYMBOL.fullmatch(symbol):
        raise ValueError(f"entrypoint symbol is invalid: {symbol}")
    return PythonEntrypointRef(path=path, symbol=symbol)


def python_entrypoint_refs(values: list[Any]) -> list[PythonEntrypointRef]:
    """Extract canonical references from direct fields and command strings."""
    refs: list[PythonEntrypointRef] = []
    for value in values:
        if isinstance(value, dict):
            candidates: list[Any] = [value]
        else:
            raw = str(value or "").strip()
            candidates = [raw] if raw and not re.search(r"\s", raw) else re.findall(
                r"[^\s\"']+\.py(?::[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)?",
                raw,
                re.IGNORECASE,
            )
        for candidate in candidates:
            try:
                parsed = parse_python_entrypoint(candidate)
            except ValueError:
                continue
            if parsed not in refs:
                refs.append(parsed)
    return refs
