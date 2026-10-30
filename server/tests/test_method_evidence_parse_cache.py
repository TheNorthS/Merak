"""Source parsing reuse must observe same-size edits and cannot cache a passing gate."""

import os

import pytest

from server.services import method_contract_evidence as evidence


@pytest.mark.parametrize('reader', [evidence._python_symbols, evidence._python_structured_data_keys])
def test_unchanged_source_reuses_parsing_but_same_metadata_edits_are_detected(tmp_path, monkeypatch, reader):
    path = tmp_path / 'study.py'
    path.write_text('def first():\n    return {"before": 1}\n')
    calls, original = [], evidence.ast.parse

    def parse(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(evidence.ast, 'parse', parse)
    first, error = reader(path)
    assert not error
    first.add('invented_by_consumer')
    second, error = reader(path)
    assert not error and 'invented_by_consumer' not in second and len(calls) == 1
    before = path.stat()
    path.write_text('def later():\n    return {"after_": 1}\n')
    os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
    assert path.stat().st_size == before.st_size
    changed, error = reader(path)
    assert not error and changed != second and len(calls) == 2
    path.unlink()
    assert reader(path)[1]


@pytest.mark.parametrize('reader', [evidence._python_symbols, evidence._python_structured_data_keys])
def test_syntax_errors_and_large_sources_are_not_cached(tmp_path, monkeypatch, reader):
    path = tmp_path / 'study.py'
    original, calls = evidence.ast.parse, []

    def parse(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(evidence.ast, 'parse', parse)
    path.write_text('def broken(:\n')
    assert reader(path)[1] and reader(path)[1] and len(calls) == 2
    path.write_text('#' + 'x' * 262_144 + '\nvalue = {"observed": 1}\n')
    assert not reader(path)[1] and not reader(path)[1] and len(calls) == 4
