"""Local producer regressions for bounded, hash-bound simulation plots."""

from __future__ import annotations

import asyncio
import hashlib
import subprocess
import threading
from pathlib import Path

import pytest

from server.services import simulation_artifact_io, simulation_render_bundle


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fixture(root: Path) -> tuple[dict, dict]:
    figures = root / "figures" / "simulated"
    data = root / "experiments" / "results" / "simulated" / "main_comparison.csv"
    figures.mkdir(parents=True)
    data.parent.mkdir(parents=True)
    data.write_text("method,value\nA,0.8\n", encoding="utf-8")
    script = figures / "simulated_main_comparison.py"
    script.write_bytes(b"# expected plot source\n")
    outputs = {kind: figures / f"simulated_main_comparison.{kind}"
               for kind in ("pdf", "svg", "png")}
    for kind, path in outputs.items():
        path.write_bytes(kind.encode())
    spec = {
        "id": "synthetic_preview_main_comparison", "stem": "simulated_main_comparison",
        "script": script, "code": script.read_text(encoding="utf-8"), "data": data,
    }
    entry = {
        "id": spec["id"], "source": script.relative_to(root).as_posix(),
        "source_sha256": _digest(script),
        "outputs": {kind: path.relative_to(root).as_posix()
                    for kind, path in outputs.items()},
        "output_sha256": {kind: _digest(path) for kind, path in outputs.items()},
    }
    previous = {
        "figure_files": [entry],
        "data_files": [{"path": data.relative_to(root).as_posix(),
                        "sha256": _digest(data)}],
    }
    return spec, previous


def test_matching_source_data_and_variants_skip_render(tmp_path: Path) -> None:
    spec, previous = _fixture(tmp_path)

    async def forbidden(_script: Path) -> tuple[bool, str]:
        pytest.fail("unchanged current figure must not be rendered again")

    result = asyncio.run(simulation_render_bundle._render_one(
        tmp_path, spec, "maximize", forbidden, previous,
    ))
    assert set(result["outputs"]) == {"pdf", "svg", "png"}


@pytest.mark.parametrize("changed", ["source", "data", "pdf", "svg", "png"])
def test_changed_input_or_variant_requires_render(tmp_path: Path, changed: str) -> None:
    spec, previous = _fixture(tmp_path)
    target = (
        Path(spec["script"]) if changed == "source"
        else Path(spec["data"]) if changed == "data"
        else Path(spec["script"]).with_suffix(f".{changed}")
    )
    target.write_bytes(b"modified")
    called: list[Path] = []

    async def render(script: Path) -> tuple[bool, str]:
        called.append(script)
        return True, ""

    asyncio.run(simulation_render_bundle._render_one(
        tmp_path, spec, "maximize", render, previous,
    ))
    assert called == [spec["script"]]


def test_absent_manifest_requires_render(tmp_path: Path) -> None:
    spec, _previous = _fixture(tmp_path)
    called = False

    async def render(_script: Path) -> tuple[bool, str]:
        nonlocal called
        called = True
        return True, ""

    asyncio.run(simulation_render_bundle._render_one(
        tmp_path, spec, "maximize", render, None,
    ))
    assert called


def test_timeout_kills_child_and_reports_bound(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    script = tmp_path / "figures" / "simulated" / "plot.py"
    script.parent.mkdir(parents=True)

    class TimedOutChild:
        killed = False
        reaped = False
        returncode = None

        def communicate(self, timeout: float | None = None) -> tuple[bytes, bytes]:
            if timeout != 5:
                raise subprocess.TimeoutExpired("plot", timeout)
            self.reaped = True
            return b"", b""

        def kill(self) -> None:
            self.killed = True

    child = TimedOutChild()
    monkeypatch.setattr(simulation_artifact_io.subprocess, "Popen", lambda *a, **k: child)
    monkeypatch.setattr(simulation_artifact_io, "local_figure_script_command", lambda _p: ["plot"])
    okay, error = asyncio.run(simulation_artifact_io.render_simulation_script(script))
    assert not okay and "180s" in error and child.killed and child.reaped


def test_cancellation_kills_child(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    script = tmp_path / "figures" / "simulated" / "plot.py"
    script.parent.mkdir(parents=True)
    entered = threading.Event()
    killed = threading.Event()

    class WaitingChild:
        returncode = None
        reaped = False

        def communicate(self, timeout: float | None = None) -> tuple[bytes, bytes]:
            if timeout == 5:
                self.reaped = True
            entered.set()
            killed.wait(2)
            return b"", b""

        def kill(self) -> None:
            killed.set()

    child = WaitingChild()
    monkeypatch.setattr(simulation_artifact_io.subprocess, "Popen", lambda *a, **k: child)
    monkeypatch.setattr(simulation_artifact_io, "local_figure_script_command", lambda _p: ["plot"])

    async def cancel() -> None:
        task = asyncio.create_task(simulation_artifact_io.render_simulation_script(script))
        assert await asyncio.to_thread(entered.wait, 2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(cancel())
    assert killed.is_set() and child.reaped


def test_cancellation_during_timeout_still_reaps_child(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    script = tmp_path / "figures" / "simulated" / "plot.py"
    script.parent.mkdir(parents=True)
    entered = threading.Event()
    killed = threading.Event()

    class RacingChild:
        returncode = None
        reaped = False

        def communicate(self, timeout: float | None = None) -> tuple[bytes, bytes]:
            if timeout != 5:
                entered.set()
                killed.wait(2)
                raise subprocess.TimeoutExpired("plot", timeout)
            self.reaped = True
            return b"", b""

        def kill(self) -> None:
            killed.set()

    child = RacingChild()
    monkeypatch.setattr(simulation_artifact_io.subprocess, "Popen", lambda *a, **k: child)
    monkeypatch.setattr(simulation_artifact_io, "local_figure_script_command", lambda _p: ["plot"])

    async def cancel() -> None:
        task = asyncio.create_task(simulation_artifact_io.render_simulation_script(script))
        assert await asyncio.to_thread(entered.wait, 2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(cancel())
    assert killed.is_set() and child.reaped
