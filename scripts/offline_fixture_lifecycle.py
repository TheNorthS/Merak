"""Bound disk use by retiring only passed test-scoped, runner-owned fixtures."""

from __future__ import annotations

import shutil
import inspect
from pathlib import Path

import pytest


def retire_passed_fixture(root: Path, candidate: Path) -> bool:
    """Never remove a root, linked target, failure evidence, or non-test directory."""
    candidate = Path(candidate)
    root = root.resolve()
    fixture_root = root / 'fixtures'
    if (not fixture_root.is_dir() or fixture_root.is_symlink()
            or getattr(fixture_root.lstat(), 'st_file_attributes', 0) & 0x400
            or fixture_root.resolve().parent != root):
        return False
    fixtures = fixture_root.resolve()
    if (not candidate.exists() or candidate.is_symlink()
            or getattr(candidate.lstat(), 'st_file_attributes', 0) & 0x400
            or not candidate.is_dir() or candidate.resolve().parent != fixtures):
        return False
    shutil.rmtree(candidate.resolve())
    return True


class PassedFixtureLifecycle:
    def __init__(self, root: Path):
        self.root = root
        self.failed: set[str] = set()
        self.passed: dict[str, set[str]] = {}
        self.cleanup_warnings: list[str] = []

    def pytest_runtest_setup(self, item):
        try:
            require_test_disk_capacity(self.root, minimum_bytes=512 * 1024 ** 2)
        except RuntimeError as error:
            pytest.exit(str(error), returncode=2)

    @pytest.hookimpl(hookwrapper=True)
    def pytest_runtest_makereport(self, item, call):
        outcome = yield
        report = outcome.get_result()
        if report.failed or report.skipped:
            self.failed.add(item.nodeid)
        elif report.passed:
            self.passed.setdefault(item.nodeid, set()).add(report.when)
        if (report.when != 'teardown' or item.nodeid in self.failed
                or self.passed.get(item.nodeid) != {'setup', 'call', 'teardown'}):
            return
        fixture_info = getattr(item, '_fixtureinfo', None)
        definitions = getattr(fixture_info, 'name2fixturedefs', {}).get('tmp_path') or []
        from _pytest.tmpdir import tmp_path as builtin_tmp_path
        if (not definitions or definitions[-1].scope != 'function'
                or getattr(definitions[-1], 'func', None) is not inspect.unwrap(builtin_tmp_path)):
            return
        candidate = (item.funcargs or {}).get('tmp_path')
        if not isinstance(candidate, Path):
            return
        try:
            retire_passed_fixture(self.root, candidate)
        except OSError as error:
            self.cleanup_warnings.append(f'{item.nodeid}: {type(error).__name__}')


def require_test_disk_capacity(repository: Path, minimum_bytes: int = 3 * 1024 ** 3) -> None:
    free = shutil.disk_usage(repository).free
    if free < minimum_bytes:
        raise RuntimeError(f'Offline verification needs at least {minimum_bytes} free bytes; available={free}. '
                           'Clean completed runner-owned fixtures before starting; no tests were launched.')
