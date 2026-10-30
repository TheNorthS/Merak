"""Repeated print preparation preserves reviewed authorship and active-source binding."""

import copy
import hashlib
import json

import pytest

from server.services import paper_print_projection as projection
from server.services.paper_gate_reporting import _state_issues
from server.tests.test_paper_print_repair import _fixture


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _files(root):
    return {path: path.read_bytes() for path in root.rglob("*") if path.is_file()}


def test_repeated_projection_reuses_the_original_reviewed_entrypoint_not_an_overlay(tmp_path, monkeypatch):
    main, section, packet = _fixture(tmp_path, monkeypatch)
    original, authored = main.read_bytes(), section.read_bytes()
    projection.install_print_projection(tmp_path, [packet])
    first = _files(tmp_path)
    projection.install_print_projection(tmp_path, [packet])
    assert projection.validate_print_projection(tmp_path) == []
    assert _files(tmp_path) == first
    assert section.read_bytes() == authored
    assert (tmp_path / "paper/derived-figures/ORIGINAL_MAIN.tex").read_bytes() == original
    assert projection.assembled_print_sha256(tmp_path) == hashlib.sha256(original).hexdigest()


def test_restored_normal_main_does_not_activate_the_obsolete_print_receipt(tmp_path, monkeypatch):
    main, section, packet = _fixture(tmp_path, monkeypatch)
    original, authored = main.read_bytes(), section.read_bytes()
    projection.install_print_projection(tmp_path, [packet])
    projection.restore_print_entrypoint(tmp_path)
    assert main.read_bytes() == original and section.read_bytes() == authored
    assert projection.validate_print_projection(tmp_path) == []
    assert projection.assembled_print_sha256(tmp_path) == hashlib.sha256(original).hexdigest()
    # An inactive receipt is historical evidence, not the current build's contract.
    (tmp_path / projection.RECEIPT).write_text("obsolete historical receipt fixture")
    before = _files(tmp_path)
    projection.restore_print_entrypoint(tmp_path)
    assert projection.validate_print_projection(tmp_path) == []
    assert projection.assembled_print_sha256(tmp_path) == _sha(main)
    assert _files(tmp_path) == before


def test_changed_normal_assembly_cannot_borrow_the_original_reviewed_main_hash(tmp_path, monkeypatch):
    main, _section, packet = _fixture(tmp_path, monkeypatch)
    reviewed = _sha(main)
    projection.install_print_projection(tmp_path, [packet])
    projection.restore_print_entrypoint(tmp_path)
    main.write_text(main.read_text() + "\nChanged generated assembly content.\n")
    assert projection.assembled_print_sha256(tmp_path) == _sha(main) != reviewed
    state = {"schema_version": 1, "scientific_freeze_id": "frozen", "source_signature": "science",
             "main_sha256": reviewed, "stages": {"assembly": {"status": "completed", "contract_version": 1}}}
    issues = _state_issues(tmp_path, {"root": tmp_path, "main": main}, state,
        {"cross_section": {"passed": True}}, 1, (), {}, lambda *_: True, lambda *_: 1,
        lambda *_: {"passed": True, "freeze_id": "frozen", "issues": []}, lambda *_: "science", lambda *_: "science")
    assert "main.tex does not match reviewed deterministic assembly" in issues


def test_projected_main_without_its_receipt_fails_even_after_restart(tmp_path, monkeypatch):
    main, _section, packet = _fixture(tmp_path, monkeypatch)
    projection.install_print_projection(tmp_path, [packet])
    (tmp_path / projection.RECEIPT).unlink()
    assert "derived-figures/" in main.read_text()
    assert any("no print projection receipt" in issue for issue in projection.validate_print_projection(tmp_path))
    with pytest.raises(ValueError, match="no print projection receipt"):
        projection.assembled_print_sha256(tmp_path)


def test_hash_updated_forged_projected_main_never_claims_reviewed_assembly(tmp_path, monkeypatch):
    main, _section, packet = _fixture(tmp_path, monkeypatch)
    projection.install_print_projection(tmp_path, [packet])
    receipt = tmp_path / projection.RECEIPT
    payload = json.loads(receipt.read_text())
    main.write_text(main.read_text() + "\nForged new scientific conclusion.\n")
    row = next(row for row in payload["sources"] if row["original_path"] == "paper/main.tex")
    row["output_sha256"] = _sha(main)
    receipt.write_text(json.dumps(payload))
    assert any("exact graphics-only transform" in issue for issue in projection.validate_print_projection(tmp_path))
    with pytest.raises(ValueError):
        projection.assembled_print_sha256(tmp_path)


def test_projection_commit_failure_restores_original_main_sources_and_receipt(tmp_path, monkeypatch):
    main, section, packet = _fixture(tmp_path, monkeypatch)
    before = _files(tmp_path)

    def fail_receipt(*_args, **_kwargs):
        raise RuntimeError("finite receipt commit failure")

    monkeypatch.setattr(projection, "atomic_write_json", fail_receipt)
    with pytest.raises(RuntimeError, match="finite receipt commit failure"):
        projection.install_print_projection(tmp_path, [packet])
    assert main.read_bytes() == before[main] and section.read_bytes() == before[section]
    assert all(path.read_bytes() == content for path, content in before.items())
    assert not (tmp_path / projection.RECEIPT).exists()


@pytest.mark.asyncio
async def test_prepare_with_no_required_variants_keeps_restored_normal_main_active(tmp_path, monkeypatch):
    from server.services import paper_print_repair
    from server.services import publication_print_contract

    main, section, packet = _fixture(tmp_path, monkeypatch)
    original, authored = main.read_bytes(), section.read_bytes()
    projection.install_print_projection(tmp_path, [packet])
    (tmp_path / "figures/FIGURE_MANIFEST.json").write_text('{"figures":[]}')

    class Contract:
        def to_dict(self):
            return {"placements": [], "contract_sha256": "0" * 64}

    monkeypatch.setattr(publication_print_contract, "read_publication_print_contract", lambda *_: Contract())
    assert await paper_print_repair.prepare_print_figures(tmp_path) == []
    assert main.read_bytes() == original and section.read_bytes() == authored
    assert projection.validate_print_projection(tmp_path) == []
    assert projection.assembled_print_sha256(tmp_path) == hashlib.sha256(original).hexdigest()
