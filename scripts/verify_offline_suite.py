"""Run the full repository test inventory without shared-state or network writes.

No model configuration is loaded. The temporary working directory owns local
databases, caches, fixtures and recovery registration; audit hooks reject any
network connection and file mutation outside that directory. This runner does
not replace scientific or acceptance gates and never resumes a user workflow.
"""

from __future__ import annotations

import json
import argparse
import os
import sys
import tempfile
import inspect
import hashlib
import xml.etree.ElementTree as ET
from pathlib import Path


REPOSITORY = Path(__file__).resolve().parents[1]


def verification_code_sha256() -> str:
    """Bind a verification receipt to the current production and test sources."""
    digest = hashlib.sha256()
    paths = [path for name in ("server", "scripts", "electron", "src", "shared", "merak-skills")
             for path in (REPOSITORY / name).rglob("*") if path.is_file()
             and path.suffix.casefold() in {".py", ".ts", ".tsx", ".js", ".cjs", ".mjs", ".md", ".tmpl"}]
    for path in sorted(paths):
        digest.update(path.relative_to(REPOSITORY).as_posix().encode())
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def _write_path(value: object, root: Path) -> None:
    if not isinstance(value, (str, bytes, os.PathLike)):
        return
    raw = os.fsdecode(value).replace("/", "\\").rstrip("\\").casefold()
    if raw in {"nul", "\\\\.\\nul", "\\\\?\\nul"}:
        return
    target = canonical_io_path(value)
    if not target.is_relative_to(canonical_io_path(root)):
        raise PermissionError(f"Offline suite cannot mutate a shared path: {target}")


def canonical_io_path(value: str | bytes | os.PathLike) -> Path:
    """Normalize Windows extended I/O spelling without widening its real boundary."""
    raw = os.fsdecode(value)
    if os.name == "nt":
        if raw.casefold().startswith("\\\\?\\unc\\"):
            raw = "\\\\" + raw[8:]
        elif raw.startswith("\\\\?\\"):
            raw = raw[4:]
    return Path(raw).resolve()


def install_guards(root: Path) -> None:
    """Enforce isolation even if an individual test misses a mock."""
    def audit(event: str, arguments: tuple) -> None:
        if event in {"socket.connect", "socket.getaddrinfo", "socket.gethostbyname"}:
            pair_frame = next((frame.frame for frame in inspect.stack(context=0)
                               if frame.function == "_fallback_socketpair"
                               and Path(frame.filename).name == "socket.py"), None)
            if (event != "socket.connect" or pair_frame is None
                    or arguments[0] is not pair_frame.f_locals.get("csock")
                    or arguments[1] != (pair_frame.f_locals.get("addr"), pair_frame.f_locals.get("port"))):
                raise PermissionError("Offline suite cannot open a network or model connection")
        if event == "open":
            path, mode, flags = arguments
            writing = isinstance(mode, str) and any(flag in mode for flag in "wax+")
            if writing or isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC):
                _write_path(path, root)
        elif event in {"os.remove", "os.rmdir", "os.mkdir", "os.chmod", "os.utime"}:
            _write_path(arguments[0], root)
        elif event in {"os.rename", "os.link", "os.symlink"}:
            for value in arguments[:2]:
                _write_path(value, root)
    sys.addaudithook(audit)


class OfflineIsolation:
    """Redirect the production watchdog's shared registry, not its decision logic."""
    def __init__(self, root: Path):
        self.root = root

    def pytest_sessionstart(self, session) -> None:
        from server.services.workflow_recovery import workflow_recovery_watchdog
        workflow_recovery_watchdog.registry_path = self.root / "recovery-projects.json"
        workflow_recovery_watchdog._projects.clear()
        workflow_recovery_watchdog._observed_at.clear()

    def pytest_runtest_logreport(self, report) -> None:
        if report.failed:
            print(f"\nOFFLINE FAILURE: {report.nodeid}\n{str(report.longrepr)[-10000:]}", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--test", action="append", default=[])
    parser.add_argument("--exclude", action="append", default=[])
    parser.add_argument("--start-after", default="")
    parser.add_argument("--stop-at", default="")
    parser.add_argument("--shard-count", type=int, default=1)
    parser.add_argument("--shard-index", type=int, default=0)
    parser.add_argument("--maxfail", type=int, default=0)
    parser.add_argument('--temp-root', type=Path, default=REPOSITORY,
                        help='Existing workspace or OS temporary directory for isolated fixtures')
    options = parser.parse_args()
    original_cwd = Path.cwd()
    tests = ([REPOSITORY / "server/tests" / name for name in options.test]
             or sorted((REPOSITORY / "server/tests").glob("test_*.py")))
    tests = [path for path in tests if path.name not in options.exclude]
    if options.start_after:
        tests = [path for path in tests if path.name > options.start_after]
    if options.stop_at:
        tests = [path for path in tests if path.name <= options.stop_at]
    if options.shard_count < 1 or not 0 <= options.shard_index < options.shard_count:
        raise ValueError("Offline shard index must belong to its positive shard count")
    tests = tests[options.shard_index::options.shard_count]
    if not tests:
        raise ValueError("Offline suite has no selected tests")
    if any(not path.is_file() or not path.resolve().is_relative_to(REPOSITORY / "server/tests") for path in tests):
        raise ValueError("Offline tests must be existing files in the canonical test directory")
    # Fail before generating fixtures, never turn an exhausted drive into hundreds
    # of misleading scientific/contract failures or lose the final JUnit receipt.
    if __package__:
        from .offline_fixture_lifecycle import require_test_disk_capacity
    else:
        from offline_fixture_lifecycle import require_test_disk_capacity
    temporary_base = options.temp_root.resolve(strict=True)
    if temporary_base != Path(tempfile.gettempdir()).resolve() and not temporary_base.is_relative_to(REPOSITORY):
        raise ValueError('Offline fixtures require the workspace or the OS temporary directory')
    require_test_disk_capacity(temporary_base)
    root = Path(tempfile.mkdtemp(prefix="offline-full-suite-", dir=temporary_base)).resolve()
    os.chdir(root)
    sys.path.insert(0, str(REPOSITORY))
    os.environ.update({"PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1", "PYTHONDONTWRITEBYTECODE": "1",
                       "TEMP": str(root), "TMP": str(root), "MPLCONFIGDIR": str(root / "matplotlib"),
                       "MERAK_DISABLE_ELECTRON_RENDERER_DISCOVERY": "1", "MERAK_ENABLE_EXTERNAL_FIGURE_RENDERERS": "0"})
    os.environ.pop("MERAK_ELECTRON_API_PORT", None)
    tempfile.tempdir = str(root)
    install_guards(root)
    import pytest
    from scripts.offline_fixture_lifecycle import PassedFixtureLifecycle
    lifecycle = PassedFixtureLifecycle(root)
    code_before = verification_code_sha256()
    print(json.dumps({"verification": "full offline suite", "test_files": len(tests),
                      "isolated_path": str(root), "network_allowed": False,
                      "shared_mutations_allowed": False, "excluded_test_files": options.exclude,
                      "start_after": options.start_after, "stop_at": options.stop_at,
                      "shard_count": options.shard_count, "shard_index": options.shard_index}), flush=True)
    result = pytest.main(["-q", "-p", "pytest_asyncio.plugin", "-p", "no:cacheprovider",
                          f"--basetemp={root / 'fixtures'}", f"--junitxml={root / 'junit.xml'}",
                          f"--maxfail={options.maxfail}", *map(str, tests)], plugins=[OfflineIsolation(root), lifecycle])
    receipt = {"pytest_exit_code": int(result), "report_path": str(root / "junit.xml"),
               "test_files": len(tests), "excluded_test_files": options.exclude,
               "start_after": options.start_after, "stop_at": options.stop_at,
               "selected_test_files": [path.name for path in tests],
               "shard_count": options.shard_count, "shard_index": options.shard_index,
               "code_sha256": code_before, "code_unchanged": code_before == verification_code_sha256(),
               "network_allowed": False, "shared_mutations_allowed": False}
    receipt['passed_fixture_cleanup_warnings'] = lifecycle.cleanup_warnings
    if (root / "junit.xml").is_file():
        suites = ET.parse(root / "junit.xml").getroot().findall("testsuite")
        receipt.update({name: sum(int(suite.get(name, "0")) for suite in suites)
                        for name in ("tests", "failures", "errors", "skipped")})
    (root / "offline-summary.json").write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    print(json.dumps(receipt), flush=True)
    os.chdir(original_cwd)
    return int(result)


if __name__ == "__main__":
    raise SystemExit(main())
