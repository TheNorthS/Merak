"""Audit interruptions preserve genuine prior calls without fallback verdicts."""

import asyncio
import hashlib
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from server.workflows import audit_coordinator as coordinator
from server.workflows.audit_layer_checkpoint import load_layer_checkpoints
from server.workflows.review_audit import AUDIT_LAYER_SKILLS
from server.workflows.review_models import AuditResult, Verdict


def _receipt(root, layer, contract, verdict=Verdict.WARN):
    directory = root / ".merak/model-api-reviewer" / f"audit-{layer}"
    directory.mkdir(parents=True, exist_ok=True)
    response = json.dumps({"verdict": verdict.value, "summary": f"layer {layer}", "evidence": ["paper/main.tex"]}).encode()
    (directory / "response.txt").write_bytes(response)
    (directory / "meta.json").write_text(json.dumps({
        "success": True, "invocation_id": f"call-{layer}", "purpose": f"audit-{AUDIT_LAYER_SKILLS[layer]}",
        "model_identity": "reviewer", "response_sha256": hashlib.sha256(response).hexdigest(),
        "evidence_packet": {"source_bundle_sha256": contract["source_hash"]},
    }))
    return AuditResult(layer, f"layer {layer}", verdict, f"layer {layer}", method="model",
        skill_name=AUDIT_LAYER_SKILLS[layer], session_id=f"call-{layer}", policy_loaded=True,
        model_name="reviewer", trace_path=directory.relative_to(root).as_posix())


@pytest.mark.asyncio
@pytest.mark.parametrize('verdict', [Verdict.FAIL, Verdict.BLOCKED])
async def test_resume_preserves_negative_conclusion_instead_of_sampling_another_verdict(tmp_path, monkeypatch, verdict):
    context = _context(tmp_path)
    contract = {'source_hash': 'source', 'runtime_signature': 'runtime', 'route_hash': 'route', 'policies': {1: 'policy'}}
    monkeypatch.setattr(coordinator, '_start_contract', lambda *_: contract)
    calls, interrupted = [], [True]
    async def invoke(ctx, number, name, operation):
        calls.append(number)
        if number == 2 and interrupted[0]:
            raise TimeoutError('transport failure')
        return _receipt(tmp_path, number, contract, verdict if number == 1 else Verdict.WARN)
    monkeypatch.setattr(coordinator, '_invoke_layer', invoke)
    with pytest.raises(TimeoutError):
        await coordinator.run_full_audit(context)
    assert load_layer_checkpoints(context, contract)[1].verdict == verdict
    interrupted[0] = False
    results = await coordinator.run_full_audit(_context(tmp_path))
    assert calls == [1, 2, 2, 3, 4, 5]
    assert results[0].verdict == verdict


def _context(root):
    chain = SimpleNamespace(_load_reusable_model_results=lambda *a, **kw: {}, _save_results=Mock(),
        _proof_detector_result=lambda *_: AuditResult(6, "Proof Checker", Verdict.NOT_APPLICABLE,
            "No formal proofs", method="deterministic_detector", skill_name="proof-checker"))
    for name in ("_audit_experiment", "_audit_result_to_claim", "_audit_paper_claims", "_audit_citations", "_audit_kill_argument"):
        setattr(chain, name, None)
    return coordinator.AuditContext(chain, str(root / "paper/main.tex"), str(root / "experiments"),
        str(root), None, "synthetic_preview", 420, "audit-run")


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [TimeoutError("model timeout"), asyncio.CancelledError(), RuntimeError("Schema error")])
async def test_restart_reuses_only_completed_layers_and_retries_failed_layer(tmp_path, monkeypatch, error):
    context = _context(tmp_path)
    contract = {"source_hash": "source", "runtime_signature": "runtime", "route_hash": "route", "policies": {1: "policy"}}
    monkeypatch.setattr(coordinator, "_start_contract", lambda *_: contract)
    calls, interrupt = [], [True]
    async def invoke(ctx, number, name, operation):
        calls.append(number)
        if number == 3 and interrupt[0]:
            raise error
        return _receipt(tmp_path, number, contract)
    monkeypatch.setattr(coordinator, "_invoke_layer", invoke)
    with pytest.raises(type(error)):
        await coordinator.run_full_audit(context)
    context.chain._save_results.assert_not_called()
    assert calls == [1, 2, 3]
    assert set(load_layer_checkpoints(context, contract)) == {1, 2}
    interrupt[0] = False
    restarted = _context(tmp_path)
    results = await coordinator.run_full_audit(restarted)
    assert calls == [1, 2, 3, 3, 4, 5]
    assert len(results) == 6 and all(result.method != "deterministic_fallback" for result in results)
    restarted.chain._save_results.assert_called_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["source", "policy", "runtime", "route", "run", "receipt", "result"])
async def test_checkpoint_rejects_changed_inputs_and_tampered_receipts(tmp_path, monkeypatch, change):
    context = _context(tmp_path)
    contract = {"source_hash": "source", "runtime_signature": "runtime", "route_hash": "route", "policies": {1: "policy"}}
    monkeypatch.setattr(coordinator, "_start_contract", lambda *_: contract)
    async def invoke(ctx, number, name, operation):
        if number == 2:
            raise TimeoutError("stopped")
        return _receipt(tmp_path, number, contract)
    monkeypatch.setattr(coordinator, "_invoke_layer", invoke)
    with pytest.raises(TimeoutError):
        await coordinator.run_full_audit(context)
    assert set(load_layer_checkpoints(context, contract)) == {1}
    if change in {"source", "runtime", "route"}:
        key = {"source": "source_hash", "runtime": "runtime_signature", "route": "route_hash"}[change]
        contract = {**contract, key: "changed"}
    elif change == "policy":
        contract = {**contract, "policies": {1: "changed"}}
    elif change == "run":
        context.run_id = "different-run"
    elif change == "receipt":
        (tmp_path / ".merak/model-api-reviewer/audit-1/response.txt").write_text('{"verdict":"PASS"}')
    else:
        path = next((tmp_path / ".merak/audit-checkpoints").glob("*.json"))
        saved = json.loads(path.read_text())
        saved["layers"][0]["result"]["summary"] = "tampered"
        path.write_text(json.dumps(saved))
    assert load_layer_checkpoints(context, contract) == {}


@pytest.mark.asyncio
async def test_parse_error_is_interruption_without_fallback_or_commit(tmp_path, monkeypatch):
    context = _context(tmp_path)
    async def invoke(*_args):
        return AuditResult(1, "Audit", Verdict.ERROR, "Invalid output schema", method="parse_error")
    monkeypatch.setattr(coordinator, "_invoke_layer", invoke)
    with pytest.raises(RuntimeError, match="Resume this layer"):
        await coordinator._run_scientific_layer(context, 1, "Audit", None, None)


@pytest.mark.asyncio
async def test_proof_timeout_resumes_after_five_saved_scientific_layers(tmp_path, monkeypatch):
    context = _context(tmp_path)
    context.chain._proof_detector_result = lambda *_: None
    contract = {"source_hash": "source", "runtime_signature": "runtime", "route_hash": "route", "policies": {1: "policy"}}
    monkeypatch.setattr(coordinator, "_start_contract", lambda *_: contract)
    calls, proof_calls = [], []
    async def layer(ctx, number, *_):
        calls.append(number)
        return _receipt(tmp_path, number, contract)
    async def proof(ctx):
        proof_calls.append(6)
        if len(proof_calls) == 1:
            raise TimeoutError("proof timeout")
        return _receipt(tmp_path, 6, contract)
    monkeypatch.setattr(coordinator, "_invoke_layer", layer)
    monkeypatch.setattr(coordinator, "_invoke_proof", proof)
    with pytest.raises(TimeoutError, match="proof timeout"):
        await coordinator.run_full_audit(context)
    assert set(load_layer_checkpoints(context, contract)) == {1, 2, 3, 4, 5}
    results = await coordinator.run_full_audit(context)
    assert calls == [1, 2, 3, 4, 5] and proof_calls == [6, 6]
    assert results[-1].method == "model"
