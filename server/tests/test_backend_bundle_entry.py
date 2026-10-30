"""Pure checks for the frozen desktop backend's command dispatch."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest
import yaml


ENTRY_PATH = Path(__file__).resolve().parents[2] / "scripts" / "merak_backend_entry.py"
PROJECT_ROOT = ENTRY_PATH.parents[1]


def _load_entry():
    spec = importlib.util.spec_from_file_location("merak_backend_entry", ENTRY_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_figure_script_dispatch_preserves_script_arguments(monkeypatch: pytest.MonkeyPatch) -> None:
    entry = _load_entry()
    original_argv = sys.argv
    calls: list[tuple[str, str, list[str]]] = []

    def capture(script: str, run_name: str) -> None:
        calls.append((script, run_name, list(sys.argv)))

    monkeypatch.setattr(entry.runpy, "run_path", capture)
    assert entry.main(["--run-figure-script", str(ENTRY_PATH), "--output", "plot.png"]) == 0
    assert calls == [
        (str(ENTRY_PATH), "__main__", [str(ENTRY_PATH), "--output", "plot.png"]),
    ]
    assert sys.argv is original_argv


def test_figure_script_dispatch_rejects_missing_source() -> None:
    entry = _load_entry()
    missing = ENTRY_PATH.with_name("absent-merak-backend-figure.py")
    assert not missing.exists()
    with pytest.raises(SystemExit, match="Figure script does not exist"):
        entry.main(["--run-figure-script", str(missing)])


def test_unknown_server_option_fails_before_backend_import() -> None:
    entry = _load_entry()
    with pytest.raises(SystemExit, match="2"):
        entry.main(["--unknown-option"])


def test_installer_requires_a_matching_bundled_backend() -> None:
    package = json.loads((PROJECT_ROOT / "package.json").read_text(encoding="utf-8"))
    build = package["scripts"]["build"]
    assert build.index("npm run build:backend") < build.index("electron-builder --win --x64")

    config = yaml.safe_load((PROJECT_ROOT / "electron-builder.yml").read_text(encoding="utf-8"))
    assert config["beforePack"] == "scripts/build-backend.js"
    resources = {resource["to"]: resource["from"] for resource in config["extraResources"]}
    assert resources["server-bundle/runtime/win32-x64"] == "resources/server-bundle/runtime/win32-x64"
    assert "afterInstall" not in config
    assert "script" not in config["nsis"]
