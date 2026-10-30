"""A global length defect needs legal author edits rather than repeated reviewer calls."""
from types import SimpleNamespace

from server.services.paper_length_findings import length_findings


def test_global_length_reduction_has_bounded_author_targets_and_keeps_threshold():
    specs = [SimpleNamespace(id=name, filename=name + '.tex', minimum_words=100) for name in ['method', 'experiments']]
    sections = {'method': 'word ' * 400, 'experiments': 'word ' * 300}
    profile = {'main_text_words': [200, 600]}
    findings = length_findings(specs, sections, profile)
    assert {item['stage_id'] for item in findings} == {'method', 'experiments'}
    assert sum(item['target_section_words'] for item in findings) <= 600
    assert all(item['target_section_words'] >= 100 for item in findings)
    assert all(item['target_files'] == [f"paper/sections/{item['stage_id']}.tex"] for item in findings)
    assert profile['main_text_words'] == [200, 600]
    assert length_findings(specs, {'method': 'word ' * 300, 'experiments': 'word ' * 300}, profile) == []
