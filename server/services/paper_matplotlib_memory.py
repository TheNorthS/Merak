"""Scoped cold Matplotlib import without persistent configuration/font caches.

Only two known installed-module function code objects are replaced in memory
while their modules initialize. Loader get_code supports frozen bytecode as
well as source installations. Public functions and cache wrappers are restored
on exit; no third-party files, Python paths or global filesystem APIs change.
"""

from __future__ import annotations

from contextlib import contextmanager
import importlib.abc
import importlib.machinery
import sys
import threading
from types import CodeType, FunctionType
from typing import Any, Iterator


def _readonly_config(xdg_base_getter):
    return _merak_readonly_pixel_cache


def _readonly_fonts(*, try_read_cache=True):
    return FontManager()


_REPLACEMENTS = {
    "matplotlib": ("_get_config_or_cache_dir", _readonly_config.__code__, (1, 0)),
    "matplotlib.font_manager": ("_load_fontmanager", _readonly_fonts.__code__, (0, 1)),
}


def _replace_code(code: CodeType, name: str, replacement: CodeType,
                  signature: tuple[int, int], found: list[CodeType]) -> CodeType:
    constants = []
    for value in code.co_consts:
        if isinstance(value, CodeType) and value.co_name == name:
            if (value.co_argcount, value.co_kwonlyargcount) != signature or value.co_freevars:
                raise ValueError("Installed Matplotlib cache function signature is unsupported")
            found.append(value)
            constants.append(replacement.replace(co_name=name, co_qualname=value.co_qualname))
        elif isinstance(value, CodeType):
            constants.append(_replace_code(value, name, replacement, signature, found))
        else:
            constants.append(value)
    return code.replace(co_consts=tuple(constants))


class _MemoryModuleLoader(importlib.abc.Loader):
    def __init__(self, loader: Any, name: str, owner: Any):
        self.loader, self.name, self.owner = loader, name, owner

    def create_module(self, spec):
        create = getattr(self.loader, "create_module", None)
        return create(spec) if create is not None else None

    def exec_module(self, module) -> None:
        get_code = getattr(self.loader, "get_code", None)
        code = get_code(self.name) if get_code is not None else None
        if not isinstance(code, CodeType):
            raise ValueError("Installed Matplotlib loader cannot provide verifiable module bytecode")
        name, replacement, signature = _REPLACEMENTS[self.name]
        found: list[CodeType] = []
        transformed = _replace_code(code, name, replacement, signature, found)
        if len(found) != 1:
            raise ValueError("Installed Matplotlib has an ambiguous or missing cache initializer")
        module.__dict__["_merak_readonly_pixel_cache"] = self.owner.cache_path
        self.owner.loaded.append((module, name, found[0]))
        exec(transformed, module.__dict__)

    def __getattr__(self, name):
        return getattr(self.loader, name)


class _MemoryCacheFinder(importlib.abc.MetaPathFinder):
    def __init__(self, cache_path: str):
        self.cache_path, self.thread = cache_path, threading.get_ident()
        self.loaded: list[tuple[Any, str, CodeType]] = []

    def find_spec(self, fullname, path=None, target=None):
        if fullname not in _REPLACEMENTS or threading.get_ident() != self.thread:
            return None
        for finder in sys.meta_path:
            if finder is self:
                continue
            find = getattr(finder, "find_spec", None)
            spec = find(fullname, path, target) if find is not None else None
            if spec is not None:
                if spec.loader is None or not callable(getattr(spec.loader, "get_code", None)):
                    raise ValueError("Installed Matplotlib loader lacks bytecode access")
                spec.loader = _MemoryModuleLoader(spec.loader, fullname, self)
                return spec
        raise ImportError("Current installed Matplotlib module cannot be located")

    def restore(self) -> None:
        for module, name, code in reversed(self.loaded):
            current = module.__dict__.get(name)
            if isinstance(current, FunctionType):
                restored = FunctionType(code, module.__dict__, name, current.__defaults__, current.__closure__)
                restored.__kwdefaults__ = current.__kwdefaults__
                module.__dict__[name] = restored
            module.__dict__.pop("_merak_readonly_pixel_cache", None)
            if module.__name__ == "matplotlib":
                for public, label in (("get_configdir", "CONFIGDIR=%s"), ("get_cachedir", "CACHEDIR=%s")):
                    function = module.__dict__.get(public)
                    original = getattr(function, "__wrapped__", None)
                    if original is not None:
                        module.__dict__[public] = module._logged_cached(label, original)
            if isinstance(module.__loader__, _MemoryModuleLoader):
                module.__loader__ = module.__loader__.loader
                module.__spec__.loader = module.__loader__


@contextmanager
def readonly_matplotlib_imports(cache_path: str) -> Iterator[None]:
    """Suppress only optional cache persistence during cold trusted verification."""
    finder = _MemoryCacheFinder(cache_path)
    sys.meta_path.insert(0, finder)
    try:
        yield
    finally:
        sys.meta_path.remove(finder)
        finder.restore()
