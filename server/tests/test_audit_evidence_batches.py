"""Large audits retain complete source coverage and cannot waive partial blockers."""

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture(autouse=True)
def fixed_reviewer_route(monkeypatch):
    monkeypatch.setattr('server.workflows.review_audit.audit_reviewer_route',
                        lambda: {'reviewer': {'resolved': True, 'model_identity': 'fixed-reviewer'}})

from server.workflows.audit_batch_receipts import verify_batch_receipt
from server.workflows.audit_evidence_batches import evidence_batches, invoke_batched_audit
from server.workflows.review_audit import _source_bundle


def _sources(root):
    paths = []
    for name, count in (("paper/main.tex", 20), ("experiments/src/train.py", 360000),
                        ("experiments/src/test_train.py", 360000)):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x" * count)
        paths.append(path)
    return paths


def test_current_matrix_and_independent_proof_repeat_in_every_batch(tmp_path):
    paths=_sources(tmp_path)
    for name in ('accepted_matrix.json','independent-matrix-audit.json','references.bib'):
        p=tmp_path/name;p.write_text('{"matrix_id":"current","passed":true}');paths.append(p)
    batches=evidence_batches(paths)
    assert len(batches)==2
    assert all(set(paths[-3:])<=set(group) for group in batches)


class Reviewer:
    def __init__(self, root, *, omit=False, verdict="WARN", mutate=None, final_verdict=None):
        self.root, self.omit, self.verdict, self.mutate = root, omit, verdict, mutate
        self.calls = []
        self.final_verdict = final_verdict

    async def invoke(self, **kwargs):
        self.calls.append(kwargs)
        index = len(self.calls)
        directory = self.root / ".merak/model-api-reviewer" / str(index)
        directory.mkdir(parents=True)
        final = "-part-" not in kwargs["purpose"]
        response = {"verdict": "WARN" if final and self.omit else self.verdict,
                    "summary": "Scoped model finding", "draft_blockers": [] if final and self.omit else ["Concrete defect"]}
        raw = json.dumps(response).encode()
        if final and self.final_verdict:
            response["verdict"] = self.final_verdict
            raw = json.dumps(response).encode()
        (directory / "response.txt").write_bytes(raw)
        digest, paths = _source_bundle(self.root, kwargs["evidence_paths"])
        assert digest == kwargs["evidence_bundle_sha256"]
        (directory / "meta.json").write_text(json.dumps({"success": True, "purpose": kwargs["purpose"],
            "invocation_id": str(index), "model_identity": "fixed-reviewer",
            "response_sha256": hashlib.sha256(raw).hexdigest(), "evidence_packet": {
                "source_bundle_sha256": digest, "paths": [p.relative_to(self.root).as_posix() for p in paths],
                "truncated_paths": []}}))
        if self.mutate and index == 1:
            self.mutate.write_text("concurrent change")
        return SimpleNamespace(text=raw.decode(), trace_path=str(directory), invocation_id=str(index),
                               model_identity="fixed-reviewer")


async def _invoke(root, reviewer, paths):
    digest, paths = _source_bundle(root, paths)
    return await invoke_batched_audit(reviewer=reviewer, project_path=str(root), skill="experiment-audit",
        prompt="Audit exact evidence", schema={}, paths=paths, source_hash=digest, timeout=60, activity=None)


@pytest.mark.asyncio
async def test_complete_batches_repeat_manuscript_and_bind_final_receipt(tmp_path):
    paths = _sources(tmp_path)
    reviewer = Reviewer(tmp_path)
    result = await _invoke(tmp_path, reviewer, paths)
    assert len(reviewer.calls) == 3
    assert all(paths[0] in call["evidence_paths"] for call in reviewer.calls[:2])
    assert set().union(*(set(call["evidence_paths"]) for call in reviewer.calls[:2])) == set(paths)
    assert all(call["timeout_seconds"] <= 60 for call in reviewer.calls)
    assert "not all original files" in reviewer.calls[-1]["prompt"]
    digest = _source_bundle(tmp_path, paths)[0]
    assert verify_batch_receipt(tmp_path, Path(result.trace_path), digest)
    paths[-1].write_text("changed after review")
    with pytest.raises(ValueError, match="evidence changed"):
        verify_batch_receipt(tmp_path, Path(result.trace_path), digest)


@pytest.mark.asyncio
async def test_synthesis_cannot_omit_partial_blockers(tmp_path):
    with pytest.raises(ValueError, match="omitted.*blocker"):
        await _invoke(tmp_path, Reviewer(tmp_path, omit=True), _sources(tmp_path))


@pytest.mark.asyncio
async def test_concurrent_source_change_stops_before_synthesis(tmp_path):
    paths = _sources(tmp_path)
    reviewer = Reviewer(tmp_path, mutate=paths[1])
    with pytest.raises(ValueError, match="inputs or reviewer identity changed"):
        await _invoke(tmp_path, reviewer, paths)
    assert len(reviewer.calls) == 2


@pytest.mark.asyncio
async def test_tampered_partial_report_invalidates_synthesis(tmp_path):
    paths = _sources(tmp_path)
    result = await _invoke(tmp_path, Reviewer(tmp_path), paths)
    directory = Path(result.trace_path)
    manifest = json.loads((directory / "audit-batches.json").read_bytes())
    (tmp_path / manifest["parts"][0]["summary"]).write_text('{}')
    with pytest.raises(ValueError, match="modified"):
        verify_batch_receipt(tmp_path, directory, _source_bundle(tmp_path, paths)[0])


def test_single_oversize_file_is_not_silently_truncated(tmp_path):
    path = tmp_path / "large.py"
    path.write_text("x" * 650001)
    with pytest.raises(ValueError, match="section splitting"):
        evidence_batches([path])


@pytest.mark.asyncio
async def test_small_audit_keeps_existing_single_native_call(tmp_path):
    path = tmp_path / "main.tex"
    path.write_text("Scientific claim")
    reviewer = Reviewer(tmp_path)
    result = await _invoke(tmp_path, reviewer, [path])
    assert len(reviewer.calls) == 1
    assert not (Path(result.trace_path) / "audit-batches.json").exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("verdict", ["ERROR", "BLOCKED", "FAIL", "WARN"])
async def test_partial_verdict_cannot_be_upgraded(tmp_path, verdict):
    with pytest.raises(ValueError, match="upgraded"):
        await _invoke(tmp_path, Reviewer(tmp_path, verdict=verdict, final_verdict="PASS"), _sources(tmp_path))


@pytest.mark.asyncio
async def test_missing_batch_receipt_cannot_validate_draft_result(tmp_path):
    from server.workflows.draft_review_evidence import draft_response_matches

    result = await _invoke(tmp_path, Reviewer(tmp_path), _sources(tmp_path))
    directory = Path(result.trace_path)
    (directory / "output.schema.json").write_text('{"required":["draft_blockers"]}')
    (directory / "audit-batches.json").unlink()
    assert not draft_response_matches(tmp_path, {"trace_path": str(directory), "skill_name": "experiment-audit",
        "model_name": result.model_identity, "session_id": result.invocation_id, "draft_blockers": ["Concrete defect"],
        "summary": "Scoped model finding", "verdict": "WARN"})


@pytest.mark.asyncio
async def test_network_failure_in_second_batch_reuses_first_with_negative_verdict(tmp_path):
    paths = _sources(tmp_path)
    reviewer = Reviewer(tmp_path, verdict='FAIL')
    original = reviewer.invoke
    failed = [False]
    purposes = []
    async def invoke(**kwargs):
        purposes.append(kwargs['purpose'])
        if kwargs['purpose'].endswith('-part-2') and not failed[0]:
            failed[0] = True
            raise TimeoutError('interrupted second batch')
        return await original(**kwargs)
    reviewer.invoke = invoke
    with pytest.raises(TimeoutError):
        await _invoke(tmp_path, reviewer, paths)
    result = await _invoke(tmp_path, reviewer, paths)
    assert purposes == ['audit-experiment-audit-part-1','audit-experiment-audit-part-2',
                        'audit-experiment-audit-part-2','audit-experiment-audit']
    assert json.loads(result.text)['verdict'] == 'FAIL'
    assert json.loads(result.text)['draft_blockers'] == ['Concrete defect']


@pytest.mark.asyncio
async def test_tampered_partial_checkpoint_blocks_retry_without_resampling(tmp_path):
    paths = _sources(tmp_path)
    reviewer = Reviewer(tmp_path)
    result = await _invoke(tmp_path, reviewer, paths)
    checkpoint = next((tmp_path/'.merak/audit-batch-checkpoints').glob('*.json'))
    data = json.loads(checkpoint.read_bytes())
    trace = tmp_path/data['parts']['1']['trace']/'response.txt'
    trace.write_text('{"verdict":"PASS","draft_blockers":[]}')
    count = len(reviewer.calls)
    with pytest.raises(ValueError, match='receipt is invalid'):
        await _invoke(tmp_path,reviewer,paths)
    assert len(reviewer.calls) == count
