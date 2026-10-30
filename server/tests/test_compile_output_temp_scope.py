"""Compiler stdout belongs to its artifact cwd even when global TEMP is frozen."""

from __future__ import annotations

from contextlib import contextmanager
import os
from pathlib import Path
import subprocess
import sys
import tempfile

import pytest

from scripts.full_benchmark_scope import write_is_allowed
from scripts.verify_offline_suite import canonical_io_path
from server.services.local_compile_process import run_local_compile_process


@contextmanager
def _benchmark_write_policy(root: Path):
    """Use the production policy for temporary fixture writes, not a mock allowlist."""
    active = True
    attempts = []

    def check(value):
        if not isinstance(value, (str, bytes, os.PathLike)):
            return
        path = canonical_io_path(value)
        allowed = write_is_allowed(root, value, rerun_literature=False)
        attempts.append((path, allowed))
        if not allowed:
            raise PermissionError("Fixture full-benchmark policy rejects frozen root output")

    def audit(event, arguments):
        if not active:
            return
        if event == "open":
            path, mode, flags = arguments
            if (isinstance(mode, str) and any(flag in mode for flag in "wax+")
                    or isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC)):
                check(path)
        elif event in {"os.remove", "os.rmdir", "os.mkdir", "os.chmod", "os.utime"}:
            check(arguments[0])
        elif event in {"os.rename", "os.link", "os.symlink"}:
            for value in arguments[:2]:
                check(value)

    sys.addaudithook(audit)
    try:
        yield attempts
    finally:
        active = False


@pytest.mark.skipif(os.name != "nt", reason="Windows temporary-output collision regression")
def test_default_frozen_root_retries_then_real_artifact_cwd_runs_owned_process_and_cleans_output(tmp_path, monkeypatch):
    root = tmp_path / "private-benchmark-fixture"
    paper = root / "paper"
    paper.mkdir(parents=True)
    canonical = paper / "main.tex"
    canonical.write_bytes(b"Unchanged publication source.\n")
    monkeypatch.setattr(tempfile, "tempdir", str(root))
    # Bound only the deliberately reproduced obsolete default-directory defect.
    with monkeypatch.context() as collision:
        collision.setattr(tempfile, "TMP_MAX", 3)
        with _benchmark_write_policy(root) as rejected:
            with pytest.raises(FileExistsError, match="No usable temporary file name"):
                with tempfile.TemporaryFile():
                    pytest.fail("Frozen root cannot own a temporary compiler output")
    root_rejections = [(path, allowed) for path, allowed in rejected if path.parent == root]
    assert len(root_rejections) == 3 and all(not allowed for _path, allowed in root_rejections)
    assert list(root.glob("tmp*")) == []
    with _benchmark_write_policy(root) as observed:
        result = run_local_compile_process([sys.executable, "-B", "-c",
            "print('artifact-scoped compiler fixture',flush=True);raise SystemExit(7)"],
            cwd=str(paper), timeout=10)
    assert result.returncode == 7 and result.stdout == b"artifact-scoped compiler fixture\r\n"
    assert observed and all(allowed for _path, allowed in observed)
    assert any(path.parent == paper and path.name.startswith("tmp") for path, _allowed in observed)
    assert all(path.is_relative_to(paper) or path == canonical_io_path(os.devnull)
               for path, _allowed in observed)
    assert canonical.read_bytes() == b"Unchanged publication source.\n"
    assert list(paper.iterdir()) == [canonical] and list(root.iterdir()) == [paper]


@pytest.mark.skipif(os.name != "nt", reason="Windows artifact output ownership")
@pytest.mark.parametrize("artifact", ["paper", "slides"])
def test_explicit_artifact_directory_wins_over_an_unusable_global_temp(tmp_path, monkeypatch, artifact):
    work = tmp_path / artifact
    work.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path / "absent-global-temp"))
    observed = []
    original = tempfile.TemporaryFile

    def capture_tempfile(*args, **kwargs):
        observed.append(kwargs.get("dir"))
        return original(*args, **kwargs)

    monkeypatch.setattr(tempfile, "TemporaryFile", capture_tempfile)
    result = run_local_compile_process([sys.executable, "-B", "-c", "print('owned artifact',flush=True)"],
        cwd=str(work), timeout=10)
    assert result.returncode == 0 and b"owned artifact" in result.stdout
    assert observed == [str(work)] and list(work.iterdir()) == []
    assert not (tmp_path / "absent-global-temp").exists()


@pytest.mark.skipif(os.name != "nt", reason="Windows existing optional-cwd contract")
def test_none_cwd_preserves_regular_unprotected_default_temp_semantics(tmp_path, monkeypatch):
    default = tmp_path / "regular-default-temp"
    default.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(default))
    observed = []
    original = tempfile.TemporaryFile

    def capture_tempfile(*args, **kwargs):
        observed.append(kwargs.get("dir", "argument-absent"))
        return original(*args, **kwargs)

    monkeypatch.setattr(tempfile, "TemporaryFile", capture_tempfile)
    result = run_local_compile_process([sys.executable, "-B", "-c", "print('regular default')"], cwd=None, timeout=10)
    assert result.returncode == 0 and b"regular default" in result.stdout
    assert observed == [None] and list(default.iterdir()) == []


@pytest.mark.skipif(os.name != "nt", reason="Windows no temporary-output fallback")
def test_missing_explicit_cwd_fails_before_process_launch_without_creating_or_falling_back(tmp_path, monkeypatch):
    work = tmp_path / "missing-artifact"
    observed = []
    original = tempfile.TemporaryFile

    def capture_tempfile(*args, **kwargs):
        observed.append(kwargs.get("dir"))
        return original(*args, **kwargs)

    def forbidden_launch(*_args, **_kwargs):
        pytest.fail("A missing explicit artifact owner must fail before process launch")

    monkeypatch.setattr(tempfile, "TemporaryFile", capture_tempfile)
    monkeypatch.setattr(subprocess, "Popen", forbidden_launch)
    with pytest.raises(FileNotFoundError):
        run_local_compile_process([sys.executable, "-B", "-c", "print('must not run')"], cwd=str(work), timeout=10)
    assert observed == [str(work)] and not work.exists()
