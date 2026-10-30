"""Cleanup cannot target user projects or destroy failed-test evidence."""

from pathlib import Path
import inspect
from types import SimpleNamespace

import pytest

from scripts.offline_fixture_lifecycle import PassedFixtureLifecycle, require_test_disk_capacity, retire_passed_fixture
from _pytest.tmpdir import tmp_path as builtin_tmp_path


def test_only_direct_owned_passed_fixture_can_be_retired(tmp_path):
    fixture = tmp_path / 'fixtures/test_passed0'
    fixture.mkdir(parents=True)
    (fixture / 'data.bin').write_bytes(b'generated')
    assert retire_passed_fixture(tmp_path, fixture)
    assert not fixture.exists()
    assert (tmp_path / 'fixtures').exists()


@pytest.mark.parametrize('kind', ['root', 'fixtures', 'outside', 'nested'])
def test_cleanup_refuses_broad_or_unowned_paths(tmp_path, kind):
    fixture_root = tmp_path / 'fixtures'
    fixture_root.mkdir()
    paths = {'root': tmp_path, 'fixtures': fixture_root, 'outside': tmp_path / 'user-project',
             'nested': fixture_root / 'test_owned0/nested'}
    path = paths[kind]
    path.mkdir(parents=True, exist_ok=True)
    sentinel = path / 'keep.txt'
    sentinel.write_text('preserve')
    assert retire_passed_fixture(tmp_path, path) is False
    assert sentinel.read_text() == 'preserve'


def _report(plugin, item, report):
    hook = plugin.pytest_runtest_makereport(item, None)
    next(hook)
    try:
        hook.send(SimpleNamespace(get_result=lambda: report))
    except StopIteration:
        pass


@pytest.mark.parametrize('failed,skipped', [(True, False), (False, True), (False, False)])
def test_evidence_retained_until_complete_successful_teardown(tmp_path, failed, skipped):
    fixture = tmp_path / 'fixtures/test_case0'
    fixture.mkdir(parents=True)
    item = SimpleNamespace(nodeid='test_case', funcargs={'tmp_path': fixture},
                           _fixtureinfo=SimpleNamespace(name2fixturedefs={'tmp_path': [SimpleNamespace(
                               scope='function', func=inspect.unwrap(builtin_tmp_path))]}))
    plugin = PassedFixtureLifecycle(tmp_path)
    _report(plugin, item, SimpleNamespace(failed=False, skipped=False, passed=True, when='setup'))
    _report(plugin, item, SimpleNamespace(failed=failed, skipped=skipped, passed=not failed and not skipped, when='call'))
    assert fixture.exists()
    _report(plugin, item, SimpleNamespace(failed=False, skipped=False, passed=True, when='teardown'))
    assert fixture.exists() == (failed or skipped)


def test_low_disk_capacity_stops_before_fixture_generation(tmp_path, monkeypatch):
    from scripts import offline_fixture_lifecycle
    monkeypatch.setattr(offline_fixture_lifecycle.shutil, 'disk_usage', lambda *_: SimpleNamespace(free=255))
    with pytest.raises(RuntimeError, match='no tests were launched'):
        require_test_disk_capacity(tmp_path, minimum_bytes=256)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize('scope,stages', [('module', ['setup', 'call', 'teardown']),
                                         ('session', ['setup', 'call', 'teardown']),
                                         ('function', ['setup', 'teardown'])])
def test_shared_or_incompletely_tested_fixtures_are_never_retired(tmp_path, scope, stages):
    fixture = tmp_path / 'fixtures/test_case0'
    fixture.mkdir(parents=True)
    item = SimpleNamespace(nodeid='test_case', funcargs={'tmp_path': fixture},
                           _fixtureinfo=SimpleNamespace(name2fixturedefs={'tmp_path': [SimpleNamespace(
                               scope=scope, func=inspect.unwrap(builtin_tmp_path))]}))
    plugin = PassedFixtureLifecycle(tmp_path)
    for stage in stages:
        _report(plugin, item, SimpleNamespace(failed=False, skipped=False, passed=True, when=stage))
    assert fixture.exists()


def test_custom_function_scoped_tmp_path_is_not_automatically_deleted(tmp_path):
    fixture = tmp_path / 'fixtures/test_shared0'
    fixture.mkdir(parents=True)
    item = SimpleNamespace(nodeid='test_custom', funcargs={'tmp_path': fixture},
                           _fixtureinfo=SimpleNamespace(name2fixturedefs={'tmp_path': [SimpleNamespace(
                               scope='function', func=lambda: fixture)]}))
    plugin = PassedFixtureLifecycle(tmp_path)
    for stage in ('setup', 'call', 'teardown'):
        _report(plugin, item, SimpleNamespace(failed=False, skipped=False, passed=True, when=stage))
    assert fixture.exists()


def test_linked_fixture_anchor_cannot_redirect_cleanup_to_user_directory(tmp_path, monkeypatch):
    fixture = tmp_path / 'fixtures/test_case0'
    fixture.mkdir(parents=True)
    original = Path.is_symlink
    monkeypatch.setattr(Path, 'is_symlink', lambda path: path == tmp_path / 'fixtures' or original(path))
    assert retire_passed_fixture(tmp_path, fixture) is False
    assert fixture.exists()
