"""Lock identity and genuine process-contention regressions; temporary data only."""

from __future__ import annotations

import json
import multiprocessing
import os
import time
from pathlib import Path, PureWindowsPath
from types import SimpleNamespace

import pytest

from server.utils import atomic_write as atomic_files
from server.utils import path_lock_identity as identity


@pytest.mark.parametrize("ordinary,extended", [
    (r"D:\study\NODE_RISK_AUDIT.json", r"\\?\D:\study\NODE_RISK_AUDIT.json"),
    (r"d:\STUDY\node_risk_audit.json", r"\\?\D:\study\NODE_RISK_AUDIT.json"),
    (r"\\host\share\study\index.json", r"\\?\UNC\host\share\study\index.json"),
    (r"\\HOST\SHARE\study\index.json", r"\\?\unc\host\share\study\index.json"),
])
def test_extended_windows_prefix_does_not_split_lock_identity(
    ordinary: str, extended: str,
) -> None:
    assert identity.resolved_lock_identity(ordinary, windows=True) == (
        identity.resolved_lock_identity(extended, windows=True)
    )


def test_atomic_lock_key_uses_the_same_windows_identity(monkeypatch) -> None:
    class ResolvedPath:
        def __init__(self, spelling: str):
            self.spelling = spelling

        def resolve(self) -> PureWindowsPath:
            return PureWindowsPath(self.spelling)

    monkeypatch.setattr(identity, "os", SimpleNamespace(name="nt"))
    ordinary = ResolvedPath(r"D:\study\NODE_RISK_AUDIT.json")
    extended = ResolvedPath(r"\\?\D:\study\NODE_RISK_AUDIT.json")
    assert atomic_files._key(ordinary) == atomic_files._key(extended)
    assert atomic_files._thread_lock(ordinary) is atomic_files._thread_lock(extended)


def test_lock_identity_resolves_aliases_instead_of_using_abspath(monkeypatch) -> None:
    seen: list[Path] = []
    actual = Path("resolved-real-directory") / "index.json"

    def resolve(path: Path) -> Path:
        seen.append(path)
        return actual

    monkeypatch.setattr(Path, "resolve", resolve)
    assert identity.canonical_lock_identity(Path("junction-alias/index.json")) == (
        identity.canonical_lock_identity(Path("real-alias/index.json"))
    )
    assert seen == [Path("junction-alias/index.json"), Path("real-alias/index.json")]


def test_non_equivalent_resolved_paths_remain_distinct() -> None:
    key = identity.resolved_lock_identity
    assert key(r"D:\study\one.json", windows=True) != key(
        r"\\?\D:\study\two.json", windows=True,
    )
    assert key(r"\\host\one\index.json", windows=True) != key(
        r"\\?\UNC\host\two\index.json", windows=True,
    )
    assert key(r"\\.\D:\study\index.json", windows=True) != key(
        r"D:\study\index.json", windows=True,
    )
    for namespace in (r"\\?\GLOBALROOT\Device\disk\index.json",
                      r"\\?\Volume{example}\index.json"):
        assert key(namespace, windows=True).startswith("//?/")
        assert key(namespace, windows=True) != key(namespace[4:], windows=True)
    assert key(r"\\?\literal", windows=False).startswith("//?/")


def _update_risk_index_with_identity(
    root_text: str, node_id: str, barrier, active, maximum, activity_lock, results,
) -> None:
    from server.services import risk_audit_coordinator as coordinator
    from server.services.node_risk_audit import node_risk_audit_service

    original_reader = coordinator._json

    def observed_reader(path: Path):
        with activity_lock:
            active.value += 1
            maximum.value = max(maximum.value, active.value)
        try:
            payload = original_reader(path)
            time.sleep(0.03)
            return payload
        finally:
            with activity_lock:
                active.value -= 1

    coordinator._json = observed_reader
    root = Path(root_text)
    for round_number in range(3):
        project = root / f"round-{round_number}"
        barrier.wait(timeout=10)
        node_risk_audit_service._update_index(project, {
            "node_id": node_id,
            "status": "clear",
            "blocking": False,
            "counts": {"blocker": 0, "warning": 0, "info": 0},
            "checks_executed": [f"{node_id}-check"],
            "report_path": str(project / ".merak" / "quality" / f"{node_id}.json"),
            "generated_at": time.time(),
        })
        results.put((round_number, atomic_files._key(
            project / ".merak" / "NODE_RISK_AUDIT.json",
        )))


def test_risk_index_serializes_mixed_io_spellings_across_processes(tmp_path: Path) -> None:
    context = multiprocessing.get_context("spawn")
    barrier = context.Barrier(4)
    active, maximum = context.Value("i", 0), context.Value("i", 0)
    activity_lock, results = context.Lock(), context.Queue()
    node_ids = ("results", "figure", "paper", "review")
    ordinary = str(tmp_path.resolve())
    extended = "\\\\?\\" + ordinary if os.name == "nt" else ordinary
    processes = [context.Process(
        target=_update_risk_index_with_identity,
        args=(ordinary if index % 2 else extended, node_id, barrier,
              active, maximum, activity_lock, results),
    ) for index, node_id in enumerate(node_ids)]
    for process in processes:
        process.start()
    try:
        for process in processes:
            process.join(timeout=15)
            assert process.exitcode == 0
        keys = [results.get(timeout=2) for _ in range(12)]
        assert maximum.value == 1
        for round_number in range(3):
            assert len({key for number, key in keys if number == round_number}) == 1
            index = tmp_path / f"round-{round_number}" / ".merak" / "NODE_RISK_AUDIT.json"
            assert set(json.loads(index.read_text(encoding="utf-8"))["nodes"]) == set(node_ids)
            assert not list(index.parent.glob(".*.tmp"))
    finally:
        for process in processes:
            if process.is_alive():
                process.terminate()
                process.join(timeout=5)
        results.close()
        results.join_thread()
