"""Choose the running installation's Python command for trusted local scripts."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def local_figure_script_command(script: str | Path) -> list[str]:
    """Run only a named local figure script with the current backend runtime.

    A frozen backend executable exposes a dedicated script mode. Development
    uses its own interpreter; neither path searches the system for ``python``.
    """
    source = str(Path(script).resolve())
    bundled = os.environ.get("MERAK_BACKEND_EXECUTABLE", "").strip()
    if bundled:
        executable = Path(bundled).resolve()
        if not executable.is_file() or executable != Path(sys.executable).resolve():
            raise RuntimeError("Bundled backend executable identity is invalid")
        return [str(executable), "--run-figure-script", source]
    return [sys.executable, source]


def local_experiment_python() -> str:
    """Require an explicit interpreter for local research code in a frozen app."""
    if not os.environ.get("MERAK_BACKEND_EXECUTABLE", "").strip():
        return sys.executable
    configured = os.environ.get("MERAK_EXPERIMENT_PYTHON", "").strip()
    if not configured or not Path(configured).is_file():
        raise RuntimeError(
            "Local experiment execution in the packaged app requires an explicit "
            "MERAK_EXPERIMENT_PYTHON interpreter; no system Python is searched. "
            "Configure one or select a remote execution target."
        )
    return str(Path(configured).resolve())
