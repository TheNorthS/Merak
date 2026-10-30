"""Cached manuscript acceptance must come from the current real local validator."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from server.services import paper_stage_validator_signature as signatures
from server.services.paper_draft_coordinator import DraftCoordinator
from server.services.paper_drafting import (
    AUTHOR_STAGE_ORDER, PAPER_STAGE_ORDER, PAPER_STAGE_LABELS, SECTION_BY_ID,
    PaperDraftingError, PaperDraftingService,
)
from server.tests._staged_paper_drafting_support import seed_project


def _introduction(*, valid: bool = True) -> str:
    contribution = (
        "First, we test held-out transfer against matched anchors. This claim fails if the anchors tie. "
        "Second, we test whether factorization is necessary. Equivalence of the controls falsifies this mechanism claim."
        if valid else "First, we propose an effective method. Second, we provide a broad benchmark."
    )
    context = (
        "The scientific comparison fixes the data partitions and control conditions before interpreting outcomes. "
        "A matched evaluation preserves the independent analysis unit and distinguishes robustness from unequal opportunity. "
    )
    return (r"\section{Introduction}" + "\n\n"
            + "However, the mechanism remains unresolved. We study a controlled transfer hypothesis. "
            + context * 11 + "\n\n" + contribution + " " + context * 11
            + r"\cite{ref1,ref2,ref3,ref4,ref5,ref6,ref7}")


def _completed_intro(root: Path, *, valid: bool = True):
    seed_project(root)
    service = PaperDraftingService()
    service.prepare(root, {})
    paths = service.paths(root)
    introduction = paths["sections"] / "01_introduction.tex"
    introduction.write_text(_introduction(valid=valid), encoding="utf-8")
    # A prior accepted record is a fixture, never evidence for current reuse.
    service.mark_stage(paths, "introduction", "completed", attempt=6,
                       review={"passed": True, "issues": []})
    return service, paths, introduction


def _coordinator(root, service, paths):
    async def forbidden(*_args):
        pytest.fail("Current local cache revalidation must not invoke a model")

    return DraftCoordinator(service=service, project_path=root, direction="Local cache proof", options={},
                            invoke_stage=forbidden, emit=None, revision_issues=None, paths=paths,
                            author_order=AUTHOR_STAGE_ORDER, paper_stage_order=PAPER_STAGE_ORDER,
                            section_by_id=SECTION_BY_ID, stage_labels=PAPER_STAGE_LABELS,
                            error_factory=PaperDraftingError, directed_repair_attempts=2,
                            semantic_stall_attempts=2)


@pytest.mark.parametrize("stale", ["missing", "different"])
@pytest.mark.asyncio
async def test_old_completed_sections_require_real_review_before_no_model_reuse(tmp_path, monkeypatch, stale):
    service, paths, introduction = _completed_intro(tmp_path)
    state = json.loads(paths["state"].read_text())
    record = state["stages"]["introduction"]
    if stale == "missing":
        record.pop("validator_signature")
    else:
        record["validator_signature"] = "0" * 64
    paths["state"].write_text(json.dumps(state))
    assert not service.stage_is_current(paths, state, "introduction")
    assert not service.stage_outputs_are_current(paths, state, "introduction")
    before = introduction.read_bytes()
    calls = []
    original = service.validate_stage

    def validate(root, stage):
        calls.append(stage)
        return original(root, stage)

    monkeypatch.setattr(service, "validate_stage", validate)
    coordinator = _coordinator(tmp_path, service, paths)
    await coordinator._run_stage("introduction")
    assert calls == ["introduction"] and introduction.read_bytes() == before
    current = json.loads(paths["state"].read_text())
    assert service.stage_is_current(paths, current, "introduction")
    assert current["stages"]["introduction"]["validator_signature"] == signatures.stage_validator_signature("introduction")
    accepted_state = paths["state"].read_bytes()
    await coordinator._run_stage("introduction")
    assert calls == ["introduction"] and introduction.read_bytes() == before
    assert paths["state"].read_bytes() == accepted_state


@pytest.mark.asyncio
async def test_invalid_old_completed_cache_is_not_stamped_or_reused(tmp_path):
    service, paths, introduction = _completed_intro(tmp_path, valid=False)
    state = json.loads(paths["state"].read_text())
    state["stages"]["introduction"].pop("validator_signature")
    paths["state"].write_text(json.dumps(state))
    before = introduction.read_bytes()
    with pytest.raises(PaperDraftingError, match="falsifiable contributions"):
        await _coordinator(tmp_path, service, paths)._run_stage("introduction")
    current = json.loads(paths["state"].read_text())
    assert "validator_signature" not in current["stages"]["introduction"]
    assert not service.stage_is_current(paths, current, "introduction")
    assert introduction.read_bytes() == before


def test_real_validator_source_byte_change_invalidates_current_cached_acceptance(tmp_path, monkeypatch):
    service, paths, _introduction_path = _completed_intro(tmp_path / "project")
    state = json.loads(paths["state"].read_text())
    assert service.stage_is_current(paths, state, "introduction")
    root = Path(signatures.__file__).parent
    replica = tmp_path / "services"
    replica.mkdir()
    for name in ("paper_stage_validator_signature.py", "manuscript_text.py", "manuscript_language.py",
                 "simulation_policy.py", "paper_section_review.py", "paper_asset_reference_contract.py",
                 "paper_contribution_validation.py", "paper_stage_cache_revalidation.py",
                 "paper_deferred_rebind.py", "manuscript_math_syntax.py", "paper_table_ownership.py"):
        shutil.copy2(root / name, replica / name)
    (replica.parent / "utils").mkdir()
    shutil.copy2(root.parent / "utils/runtime_source_root.py", replica.parent / "utils/runtime_source_root.py")
    monkeypatch.setattr(signatures, "server_source_root", lambda: replica.parent)
    assert service.stage_is_current(paths, state, "introduction")
    validator = replica / "paper_contribution_validation.py"
    validator.write_bytes(validator.read_bytes() + b"\n# Pure fixture implementation change.\n")
    assert not service.stage_is_current(paths, state, "introduction")
    assert not service.stage_outputs_are_current(paths, state, "introduction")


def test_completed_status_without_an_actual_passed_review_cannot_create_signature(tmp_path):
    seed_project(tmp_path)
    service = PaperDraftingService()
    service.prepare(tmp_path, {})
    paths = service.paths(tmp_path)
    (paths["sections"] / "01_introduction.tex").write_text(_introduction())
    state = service.mark_stage(paths, "introduction", "completed", attempt=0)
    assert "validator_signature" not in state["stages"]["introduction"]
    assert not service.stage_is_current(paths, state, "introduction")


def _frozen_sources(root: Path, monkeypatch) -> Path:
    import sys
    from server.utils.runtime_source_root import server_source_root

    source = server_source_root()
    mirror = root / "merak-source/server"
    services = mirror / "services"
    services.mkdir(parents=True)
    for name in ("paper_stage_validator_signature.py", "manuscript_text.py", "manuscript_language.py",
                 "simulation_policy.py", "paper_section_review.py", "paper_asset_reference_contract.py",
                 "paper_contribution_validation.py", "paper_stage_cache_revalidation.py",
                 "paper_deferred_rebind.py", "manuscript_math_syntax.py", "paper_table_ownership.py"):
        shutil.copy2(source / "services" / name, services / name)
    (mirror / "utils").mkdir()
    shutil.copy2(source / "utils/runtime_source_root.py", mirror / "utils/runtime_source_root.py")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(root), raising=False)
    return services


def test_frozen_bundle_uses_declared_source_mirror_not_module_pseudo_path(tmp_path, monkeypatch):
    expected = signatures.stage_validator_signature("introduction")
    mirror = _frozen_sources(tmp_path, monkeypatch)
    monkeypatch.setattr(signatures, "__file__", str(tmp_path / "server/services/pseudo.pyc"))
    assert signatures.stage_validator_signature("introduction") == expected
    assert (mirror / "paper_contribution_validation.py").is_file()


def test_changed_frozen_validator_bytes_invalidate_current_cache(tmp_path, monkeypatch):
    service, paths, _introduction_path = _completed_intro(tmp_path / "project")
    state = json.loads(paths["state"].read_text())
    mirror = _frozen_sources(tmp_path / "executable", monkeypatch)
    assert service.stage_is_current(paths, state, "introduction")
    source = mirror / "paper_contribution_validation.py"
    source.write_bytes(source.read_bytes() + b"\n# Frozen fixture implementation change.\n")
    assert not service.stage_is_current(paths, state, "introduction")
    assert not service.stage_outputs_are_current(paths, state, "introduction")


def test_missing_frozen_validator_source_fails_closed_without_cache_stamp(tmp_path, monkeypatch):
    service, paths, _introduction_path = _completed_intro(tmp_path / "project")
    state = json.loads(paths["state"].read_text())
    before = paths["state"].read_bytes()
    mirror = _frozen_sources(tmp_path / "executable", monkeypatch)
    (mirror / "paper_contribution_validation.py").unlink()
    with pytest.raises((FileNotFoundError, RuntimeError)):
        service.stage_is_current(paths, state, "introduction")
    assert paths["state"].read_bytes() == before


def test_changed_frozen_source_resolver_invalidates_cached_acceptance(tmp_path, monkeypatch):
    service, paths, _introduction_path = _completed_intro(tmp_path / "project")
    state = json.loads(paths["state"].read_text())
    mirror = _frozen_sources(tmp_path / "executable", monkeypatch)
    assert service.stage_is_current(paths, state, "introduction")
    resolver = mirror.parent / "utils/runtime_source_root.py"
    resolver.write_bytes(resolver.read_bytes() + b"\n# Frozen fixture source-root change.\n")
    assert not service.stage_is_current(paths, state, "introduction")
