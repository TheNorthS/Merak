"""Correction authorization never grants a scientific or workflow verdict."""

import json
from pathlib import Path

import pytest

from scripts.scientific_correction_boundary import correction_baseline, digest_file, verify_correction
from scripts.live_snapshot_resume_validation import scientific_digest
from scripts.verify_live_remaining_snapshot import protected_inputs


def _write(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")


def _fixture(tmp_path: Path) -> tuple[Path, Path, Path, str]:
    original, root = tmp_path / "original", tmp_path / "copy"
    for directory, status in ((original, "cancelled"), (root, "incomplete")):
        _write(directory / ".merak/runs/test.json", json.dumps({"run_id": "test", "status": status}))
        _write(directory / ".merak/runs/test.skills.json", '{"actual_call":"preserved"}')
        _write(directory / "experiments/results/raw.csv", "model,value,ci_low,seed\na,0.5,0.4,13\n")
        _write(directory / "experiments/results/analysis.md", "Old unsupported report")
        _write(directory / "paper/sections/05_results.tex", "Old prose")
    baseline = correction_baseline(root, original, "test",
        state_pin=digest_file(root / ".merak/runs/test.json"),
        science_pin=scientific_digest(protected_inputs(root)))
    baseline_path = root / ".merak/authorized-corrections/BASELINE.json"
    _write(baseline_path, json.dumps(baseline))
    return root, original, baseline_path, digest_file(baseline_path)


def test_report_correction_preserves_all_numbers_and_never_accepts(tmp_path):
    root, original, baseline, pin = _fixture(tmp_path)
    _write(root / "experiments/results/analysis.md", "C1 unresolved; no execution evidence")
    report = verify_correction(root, original, baseline, pin)
    assert report["boundary_verified"] is True
    assert report["all_raw_results_byte_identical"] is True
    assert report["scientific_acceptance_granted"] is False
    assert report["workflow_state_and_execution_evidence_unchanged"] is True
    assert report["requires_fresh_owner_validation"]
    assert report["science_before_sha256"] != report["science_after_sha256"]


@pytest.mark.parametrize("relative", [
    "experiments/results/raw.csv", "ideas/SELECTED_IDEA.json", "figures/main.svg",
    ".merak/runs/test.json", ".merak/runs/test.skills.json", ".merak/skill-invocations/session.json",
])
def test_raw_data_acceptance_and_invocation_mutations_refused(tmp_path, relative):
    root, original, baseline, pin = _fixture(tmp_path)
    _write(root / "experiments/results/analysis.md", "Corrected report")
    _write(root / relative, "changed")
    with pytest.raises(ValueError, match="outside its explicit scope"):
        verify_correction(root, original, baseline, pin)


def test_original_change_and_baseline_rewrite_refused(tmp_path):
    root, original, baseline, pin = _fixture(tmp_path)
    _write(root / "experiments/results/analysis.md", "Corrected report")
    _write(original / "experiments/results/raw.csv", "changed")
    with pytest.raises(ValueError, match="original project"):
        verify_correction(root, original, baseline, pin)
    _write(baseline, '{}')
    with pytest.raises(ValueError, match="independently recorded"):
        verify_correction(root, original, baseline, pin)


def test_no_input_deleted_and_no_silent_noop_verification(tmp_path):
    root, original, baseline, pin = _fixture(tmp_path)
    with pytest.raises(ValueError, match="changes no inputs"):
        verify_correction(root, original, baseline, pin)
    (root / "experiments/results/analysis.md").unlink()
    with pytest.raises(ValueError, match="cannot delete"):
        verify_correction(root, original, baseline, pin)


def test_capture_refuses_unpinned_active_copy(tmp_path):
    root, original, _baseline, _pin = _fixture(tmp_path)
    with pytest.raises(ValueError, match="independently pinned"):
        correction_baseline(root, original, "test", state_pin="wrong", science_pin="wrong")


@pytest.mark.parametrize("relative", [
    "experiments/results/raw.csv", "experiments/src/data.py", ".merak/runs/test.json",
    ".merak/skill-invocations/raw.json", "paper/main.pdf", "../original/experiments/results/raw.csv",
])
def test_report_writer_refuses_raw_and_foreign_writes_before_truncation(tmp_path, relative):
    from scripts.scientific_correction_writes import correction_report_write_scope

    root, _original, _baseline, _pin = _fixture(tmp_path)
    target = root / relative
    before = target.read_bytes() if target.exists() else None
    with correction_report_write_scope(root), pytest.raises(PermissionError):
        target.write_text("must never be written", encoding="utf-8")
    assert (target.read_bytes() if target.exists() else None) == before


def test_report_writer_allows_atomic_owned_report_only(tmp_path):
    from scripts.scientific_correction_writes import correction_report_write_scope
    from server.utils.atomic_write import atomic_write_json

    root, _original, _baseline, _pin = _fixture(tmp_path)
    target = root / "experiments/results/CLAIM_DECISIONS.json"
    with correction_report_write_scope(root):
        atomic_write_json(target, {"claims": "unresolved"})
    assert json.loads(target.read_text(encoding="utf-8")) == {"claims": "unresolved"}
