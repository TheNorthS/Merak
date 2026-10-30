"""Mixed runtime and unittest records keep separate reachability obligations."""

from server.tests.test_workflow_109_static_harness import _project


def test_mixed_test_class_helpers_and_runtime_are_independently_verified(tmp_path):
    check = {'id': 'mixed', 'evidence': [
        {'path': 'experiments/src/test_pipeline.py', 'symbols': ['ContractTests', '_source', 'test_source']},
        {'path': 'experiments/src/train.py', 'symbols': ['main']}]}
    report = _project(tmp_path, 'def main():\n    return sum([1, 2])\n', '''
def _source():
    return str("real source")
class ContractTests:
    def test_source(self):
        self.assertEqual(_source(), "real source")
''', [check])
    coverage = report['implementation_checks']['mixed']
    assert coverage['passed'], coverage
    assert coverage['reachable_symbols'] == ['main']
    assert set(coverage['supporting_test_symbols']) == {'ContractTests', '_source', 'test_source'}
    assert not coverage['execution_verified']


def test_uncalled_test_helper_and_dead_runtime_remain_missing(tmp_path):
    check = {'id': 'mixed', 'evidence': [
        {'path': 'experiments/src/test_pipeline.py', 'symbols': ['unused', 'test_value']},
        {'path': 'experiments/src/train.py', 'symbols': ['dead']}]}
    report = _project(tmp_path, 'def main():\n    return 0\ndef dead():\n    return sum([1, 2])\n', '''
def unused():
    return "not called"
def test_value():
    assert 1 == 1
''', [check])
    coverage = report['implementation_checks']['mixed']
    assert not coverage['passed']
    assert set(coverage['missing_symbols']) == {'unused', 'dead'}
