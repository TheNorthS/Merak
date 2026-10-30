"""Draft semantic audit scope is bounded, complete for selected files, and explicit."""

import pytest

from server.workflows.draft_audit_evidence import draft_audit_evidence, MAX_DRAFT_AUDIT_BYTES


def _write(root, name, content):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return path


def test_draft_audit_keeps_code_claims_and_actual_results_but_discloses_unread_raw_rows(tmp_path):
    paths = [_write(tmp_path, "paper/main.tex", "Scientific claims"),
        _write(tmp_path, "experiments/src/train.py", "training code"),
        _write(tmp_path, "experiments/results/simulated/calibration.csv", "risk,risk_ci_low,risk_ci_high\n.12,.10,.14"),
        _write(tmp_path, "experiments/results/simulated/raw_predictions.jsonl", "{}\n" * 10000)]
    before = {path: path.read_bytes() for path in paths}
    digest, selected, scope = draft_audit_evidence(tmp_path, paths, "experiment-audit")
    assert set(selected) == set(paths[:3]) and len(digest) == 64
    assert "raw_predictions.jsonl" in scope and "NOT semantic evidence" in scope
    assert "Do not claim exhaustive raw-record verification" in scope
    assert all(path.read_bytes() == raw for path, raw in before.items())


def test_oversize_canonical_file_fails_before_model_call_without_truncation(tmp_path):
    path = _write(tmp_path, "experiments/src/train.py", "x" * (MAX_DRAFT_AUDIT_BYTES + 1))
    with pytest.raises(ValueError, match="split the audit"):
        draft_audit_evidence(tmp_path, [path], "experiment-audit")


def test_citation_layer_includes_retrieval_receipts_and_preserves_verification_limits(tmp_path):
    receipt = _write(tmp_path, "literature/SEARCH_EVIDENCE.json", '{"stages":{"lit":{"complete":true}}}')
    _, selected, scope = draft_audit_evidence(tmp_path, [receipt], "citation-audit")
    assert receipt in selected
    assert "prior external retrieval" in scope and "Incorrect or fabricated" in scope


def test_identical_bibliographies_remain_visible_under_their_compilation_paths(tmp_path):
    paths = [_write(tmp_path, name, '@article{ref,title={Source}}')
             for name in ('literature/references.bib', 'paper/references.bib')]
    _, selected, _ = draft_audit_evidence(tmp_path, paths, 'citation-audit')
    assert selected == paths
