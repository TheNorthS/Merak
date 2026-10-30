"""Evidence selectors agree with the call graph about exact module qualification."""

from server.services.method_contract_validation import validate_evidence_selectors


def _check(path, values):
    matched = {'path': path.name, 'data_keys': []}
    issues = validate_evidence_selectors(path, 'entrypoint', matched, {'symbols': values})
    return matched, issues


def test_module_qualified_real_functions_and_methods_are_valid(tmp_path):
    path = tmp_path / 'run_analysis.py'
    path.write_text('def main():\n    return sum([1, 2])\nclass Solver:\n    def run(self):\n        return main()\n')
    values = ['run_analysis.main', 'run_analysis.Solver.run', 'main', 'Solver.run']
    matched, issues = _check(path, values)
    assert issues == []
    assert matched['symbols'] == values


def test_wrong_module_missing_symbol_and_prose_do_not_pass(tmp_path):
    path = tmp_path / 'run_analysis.py'
    path.write_text('# def invented(): pass\n"run_analysis.invented"\ndef main():\n    return 1\n')
    for value in ['other.main', 'run_analysis.invented', 'run_analysis.main.no_such_method']:
        matched, issues = _check(path, [value])
        assert issues and matched['symbols'] == []


def test_qualified_symbol_tracks_changed_source(tmp_path):
    path = tmp_path / 'run_analysis.py'
    path.write_text('def main():\n    return 1\n')
    assert not _check(path, ['run_analysis.main'])[1]
    path.write_text('def gone():\n    return 1\n')
    assert _check(path, ['run_analysis.main'])[1]
