"""Stable fingerprints of loaded producer code, independent of CPython quickening."""

from __future__ import annotations

import hashlib
import importlib
import inspect
import json
from types import CodeType
from types import ModuleType
from typing import Any


def _constant(value: Any) -> Any:
    if isinstance(value, CodeType):
        return _code(value)
    if isinstance(value, (set, frozenset)):
        members = [_constant(item) for item in value]
        return sorted(members, key=lambda item: json.dumps(item, sort_keys=True))
    if isinstance(value, (tuple, list)):
        return [_constant(item) for item in value]
    if isinstance(value, dict):
        return {
            str(key): _constant(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, bytes):
        return {"bytes": value.hex()}
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return {"type": type(value).__qualname__, "value": repr(value)}


def _code(code: CodeType) -> dict[str, Any]:
    return {
        "bytecode": code.co_code.hex(),
        "constants": [_constant(item) for item in code.co_consts],
        "names": code.co_names,
        "variables": code.co_varnames,
        "free_variables": code.co_freevars,
        "cell_variables": code.co_cellvars,
        "argument_counts": (
            code.co_argcount, code.co_posonlyargcount,
            code.co_kwonlyargcount, code.co_nlocals,
        ),
        "flags": code.co_flags,
    }


def module_digest(module: ModuleType) -> bytes:
    """Hash the executing functions and declarative constants, not disk edits."""
    members: list[tuple[str, Any]] = []
    for owner, member in sorted(vars(module).items()):
        if getattr(member, "__module__", None) != module.__name__:
            continue
        methods = vars(member).items() if inspect.isclass(member) else ((owner, member),)
        for method_name, method in sorted(methods):
            function = getattr(method, "__func__", method)
            if inspect.isfunction(function):
                members.append((f"{owner}.{method_name}", _code(function.__code__)))
    constants = {
        key: _constant(value) for key, value in vars(module).items()
        if key.isupper() and isinstance(value, (str, int, float, tuple, list, dict, set, frozenset))
    }
    payload = json.dumps(
        {"members": members, "constants": constants},
        ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).digest()


def loaded_module_digest(name: str, package: str) -> bytes:
    """Import one owned module and fingerprint the loaded implementation."""
    return module_digest(importlib.import_module(f".{name}", package=package))
