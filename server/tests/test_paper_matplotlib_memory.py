"""Cold pixel verification uses installed bytecode without writable font caches."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys
from types import ModuleType, SimpleNamespace

import pytest

from server.services.paper_matplotlib_memory import _MemoryCacheFinder, _MemoryModuleLoader


class _FrozenCodeLoader:
    def __init__(self, code):
        self.code = code

    def get_code(self, _name):
        return self.code


def test_bytecode_only_loader_initializes_memory_font_manager_and_restores_original_function():
    source = "def FontManager(): return 'memory-fonts'\n" \
             "def _load_fontmanager(*, try_read_cache=True): raise RuntimeError('persistent-original')\n" \
             "fontManager = _load_fontmanager()\n"
    owner = _MemoryCacheFinder("unused-readonly-cache")
    loader = _FrozenCodeLoader(compile(source, "frozen-matplotlib-font-manager.pyc", "exec"))
    module = ModuleType("matplotlib.font_manager")
    wrapped = _MemoryModuleLoader(loader, module.__name__, owner)
    module.__loader__, module.__spec__ = wrapped, SimpleNamespace(loader=wrapped)
    wrapped.exec_module(module)
    assert module.fontManager == "memory-fonts"
    owner.restore()
    with pytest.raises(RuntimeError, match="persistent-original"):
        module._load_fontmanager()
    assert "_merak_readonly_pixel_cache" not in vars(module)
    assert module.__loader__ is loader and module.__spec__.loader is loader


@pytest.mark.parametrize("source", ["answer = 1", "def _load_fontmanager(other): return other",
                                    "def _load_fontmanager(*,try_read_cache=True): return 1\n"
                                    "def _load_fontmanager(*,try_read_cache=True): return 2\n"])
def test_unknown_installed_cache_initializer_does_not_execute_or_fall_back(source):
    owner = _MemoryCacheFinder("unused-readonly-cache")
    module = ModuleType("matplotlib.font_manager")
    loader = _FrozenCodeLoader(compile(source, "trusted-package.pyc", "exec"))
    with pytest.raises(ValueError, match="unsupported|ambiguous|missing"):
        _MemoryModuleLoader(loader, module.__name__, owner).exec_module(module)
    assert not hasattr(module, "answer")


_COLD_VALIDATION = r'''
from pathlib import Path
import hashlib,json,os,sys
root=Path(sys.argv[1])
packet=json.loads((root/'packet.json').read_text(encoding='utf-8'))
assert 'matplotlib' not in sys.modules
before={str(path):hashlib.sha256(path.read_bytes()).hexdigest() for path in root.rglob('*') if path.is_file()}
attempted=[]
def audit(event,args):
    writing=False
    if event=='open':
        path,mode,flags=args
        writing=isinstance(mode,str) and any(flag in mode for flag in 'wax+') or isinstance(flags,int) and flags&(os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC)
    if writing or event in {'os.remove','os.rmdir','os.mkdir','os.chmod','os.utime','os.rename','os.link','os.symlink','subprocess.Popen','socket.connect','socket.getaddrinfo','socket.gethostbyname'}:
        attempted.append(event)
        raise PermissionError('Cold proof must be fully read-only')
sys.addaudithook(audit)
from server.services.paper_derived_pixel_binding import validate_pixel_binding
issues=validate_pixel_binding(root,packet)
from server.services.paper_matplotlib_memory import _MemoryCacheFinder,_MemoryModuleLoader
import matplotlib,matplotlib.font_manager as fm
assert not any(isinstance(finder,_MemoryCacheFinder) for finder in sys.meta_path)
assert not isinstance(matplotlib.__loader__,_MemoryModuleLoader)
assert '_merak_readonly_pixel_cache' not in vars(matplotlib)
assert 'mkdir' in matplotlib._get_config_or_cache_dir.__code__.co_names
assert 'json_dump' in fm._load_fontmanager.__code__.co_names
assert not Path(os.environ['MPLCONFIGDIR']).exists()
assert not (root/'paper/derived-figures/.readonly-font-cache').exists()
after={str(path):hashlib.sha256(path.read_bytes()).hexdigest() for path in root.rglob('*') if path.is_file()}
assert before==after and not attempted
print(json.dumps({'issues':issues,'read_only':True,'public_functions_restored':True}))
'''


@pytest.mark.parametrize("wrong_pixels", [False, True])
def test_fresh_process_empty_config_directory_validates_without_attempting_persistent_writes(tmp_path, wrong_pixels):
    from server.services.paper_derived_figure_rendering import derive_paper_figure
    from server.tests.test_paper_derived_figure_rendering import _entry, _placement

    entry = _entry(tmp_path)
    packet = asyncio.run(derive_paper_figure(tmp_path, entry, _placement(tmp_path, entry)))
    if wrong_pixels:
        import fitz
        pdf = tmp_path / packet["derived_paths"]["pdf"]
        with fitz.open(pdf) as document:
            document[0].insert_text((35, 120), "Wrong outcome 0.999", fontsize=20)
            changed = document.tobytes()
        pdf.write_bytes(changed)
    (tmp_path / "packet.json").write_text(json.dumps(packet), encoding="utf-8")
    environment = {**os.environ, "MPLCONFIGDIR": str(tmp_path / "brand-new-empty-cache"),
                   "PYTHONDONTWRITEBYTECODE": "1", "PYTHONPATH": str(Path(__file__).resolve().parents[2])}
    result = subprocess.run([sys.executable, "-B", "-c", _COLD_VALIDATION, str(tmp_path)],
                            cwd=tmp_path, env=environment, capture_output=True, text=True, timeout=90)
    assert result.returncode == 0, result.stdout + result.stderr
    proof = json.loads(result.stdout.strip().splitlines()[-1])
    assert bool(proof["issues"]) is wrong_pixels
    assert proof["read_only"] and proof["public_functions_restored"]
