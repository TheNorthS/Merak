"""Trusted figure subprocesses use only the running backend's interpreter."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from server.services.backend_python_command import (
    local_experiment_python,
    local_figure_script_command,
)


def test_development_figure_command_uses_current_interpreter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("MERAK_BACKEND_EXECUTABLE", raising=False)
    script = tmp_path / "plot.py"
    assert local_figure_script_command(script) == [sys.executable, str(script)]


def test_packaged_figure_command_reuses_verified_backend_executable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    executable = tmp_path / "merak-backend.exe"
    executable.write_bytes(b"frozen-backend")
    monkeypatch.setattr(sys, "executable", str(executable))
    monkeypatch.setenv("MERAK_BACKEND_EXECUTABLE", str(executable))
    script = tmp_path / "plot.py"
    assert local_figure_script_command(script) == [
        str(executable), "--run-figure-script", str(script),
    ]


def test_packaged_figure_command_rejects_foreign_executable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    executable = tmp_path / "foreign.exe"
    executable.write_bytes(b"different")
    monkeypatch.setenv("MERAK_BACKEND_EXECUTABLE", str(executable))
    with pytest.raises(RuntimeError, match="identity is invalid"):
        local_figure_script_command(tmp_path / "plot.py")


def test_packaged_local_experiment_never_uses_implicit_python(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    executable = tmp_path / "merak-backend.exe"
    executable.write_bytes(b"frozen-backend")
    monkeypatch.setenv("MERAK_BACKEND_EXECUTABLE", str(executable))
    monkeypatch.delenv("MERAK_EXPERIMENT_PYTHON", raising=False)
    with pytest.raises(RuntimeError, match="MERAK_EXPERIMENT_PYTHON"):
        local_experiment_python()
    selected = tmp_path / "experiment-python.exe"
    selected.write_bytes(b"user-selected-interpreter")
    monkeypatch.setenv("MERAK_EXPERIMENT_PYTHON", str(selected))
    assert local_experiment_python() == str(selected)
