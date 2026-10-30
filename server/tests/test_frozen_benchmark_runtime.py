"""Explicit historical authority never changes ordinary planned reuse policy."""

from pathlib import Path

import pytest

from server.services.frozen_benchmark_runtime import _arguments
from server.services import planned_result_reuse as reuse


def test_absent_authority_retains_existing_strict_input_mismatch(tmp_path, monkeypatch):
    simulated = tmp_path / "experiments/results/simulated/SIMULATION_MANIFEST.json"
    simulated.parent.mkdir(parents=True)
    simulated.write_text("{}")
    planned = tmp_path / "planned.json"
    planned.write_text('{"schema":5,"evidence_mode":"synthetic_preview","input_bundle_sha256":"old"}')
    monkeypatch.setattr(reuse, "_current_bundle", lambda *_args: {})
    with pytest.raises(ValueError, match="does not match"):
        reuse.resolve_planned_result_reuse(tmp_path, [planned], mode="synthetic_preview", input_hash="new",
                                          target_venue="ICLR", force=False)


@pytest.mark.parametrize("mode,force", [("design_only", False), ("synthetic_preview", True)])
def test_proof_cannot_authorize_regeneration_or_other_evidence_mode(tmp_path, monkeypatch, mode, force):
    simulated = tmp_path / "experiments/results/simulated/SIMULATION_MANIFEST.json"
    simulated.parent.mkdir(parents=True)
    simulated.write_text("{}")
    planned = tmp_path / "planned.json"
    planned.write_text("{}")
    monkeypatch.setattr(reuse, "_current_bundle", lambda *_args: {})
    with pytest.raises(ValueError):
        reuse.resolve_planned_result_reuse(tmp_path, [planned], mode=mode, input_hash="new", target_venue="ICLR",
                                          force=force, frozen_authority={})


@pytest.mark.parametrize("value", [None, {}, {"schema":1,"ignore_hash":True}])
def test_no_untyped_context_can_rebind_old_evidence(value):
    with pytest.raises(ValueError, match="independently pinned"):
        _arguments(value)


def test_production_consumer_uses_readonly_authority_not_writes(tmp_path, monkeypatch):
    import json
    from server.services import frozen_benchmark_runtime as runtime

    simulated = tmp_path / "experiments/results/simulated/SIMULATION_MANIFEST.json"
    simulated.parent.mkdir(parents=True)
    simulated.write_text("{}")
    planned = tmp_path / "planned.json"
    content = '{"schema":5,"evidence_mode":"synthetic_preview","input_bundle_sha256":"old"}'
    planned.write_text(content)
    monkeypatch.setattr(reuse, "_current_bundle", lambda *_args: {})
    calls = []
    def valid(root, context, digest):
        calls.append((root, context, digest))
        return {"original_generation_input_sha256":"old","settings":{"target_venue":"ICLR"}}
    monkeypatch.setattr(runtime, "validate_reuse_authority", valid)
    generated, actual = reuse.resolve_planned_result_reuse(tmp_path,[planned],mode="synthetic_preview",
        input_hash="new",target_venue="ICLR",force=False,frozen_authority={"source":"explicit"})
    assert not generated and actual == json.loads(content)
    assert planned.read_text() == content and calls == [(tmp_path,{"source":"explicit"},"new")]
