"""Read-only source-delta review preserves an unchanged specialist artifact without reauthoring."""

import hashlib
import json
from pathlib import Path


def dependency_review_valid(root: Path, review: dict, digest: str, artifact: Path) -> bool:
    """Current dependency bytes, output and native review response must all remain bound."""
    try:
        from .review_evidence_packet import build_managed_evidence_packet
        directory = (root / review["trace_path"]).resolve()
        if not directory.is_relative_to(root / ".merak/model-api-reviewer"):
            return False
        meta = json.loads((directory / "meta.json").read_bytes())
        raw = (directory / "response.txt").read_bytes()
        response = json.loads(raw)
        _, packet = build_managed_evidence_packet(root, review["paths"],
            maximum_files=192, maximum_bytes=6_000_000, maximum_file_bytes=1_000_000)
        return bool(review["input_digest"] == digest and response.get("valid") is True
            and response.get("issues") == [] and meta.get("success") is True
            and meta.get("purpose") == "specialist-dependency-review"
            and meta.get("invocation_id") == review["invocation_id"]
            and meta.get("response_sha256") == hashlib.sha256(raw).hexdigest()
            and meta.get("evidence_packet", {}).get("source_bundle_sha256") == packet["source_bundle_sha256"]
            and review["artifact_sha256"] == hashlib.sha256(artifact.read_bytes()).hexdigest())
    except (OSError, ValueError, KeyError, TypeError):
        return False


async def review_changed_specialist_inputs(ctx, record: dict) -> None:
    """Only existing completed outputs are candidates; any invalid output needs its producer."""
    from .research_specialists import research_specialist_service as service
    from .publication_style import publication_style_service
    from .specialist_inputs import input_relatives

    root = Path(ctx.run.project_path).resolve()
    payload = service.load(root, ctx.run.id)
    if not payload:
        return
    profile = payload["profile"]
    style = publication_style_service.prepare(root, ctx.research_direction,
        target_venue=str(ctx.opts.get("target_venue") or ""),
        research_family=str(ctx.opts.get("research_family") or ""),
        study_archetype=str(ctx.opts.get("study_archetype") or ""))
    specs = {s.id: s for s in service._selected_specs(profile["family"], profile["study_archetype"])}
    for entry in payload["subnodes"]:
        if entry["id"] not in specs:
            continue
        expected = service._input_digest(root, style, specs[entry["id"]], ctx.opts)
        if entry.get("input_digest") == expected:
            continue
        artifact = root / entry["artifact"]
        repair = record.get('specialist_repairs', {}).get(entry['id'])
        candidate = repair.get('candidate') if repair and repair.get('status') == 'authored' else None
        checked = candidate or entry
        if checked.get("status") != "completed" or not service._invocation_trace_valid(root, checked)[0]:
            raise ValueError("Specialist lacks a completed prior execution: " + entry["id"])
        if not service._artifact_valid(root, checked)[0] or checked["artifact_sha256"] != service._sha256(artifact):
            raise ValueError("Specialist output changed; source review cannot replace producer repair")
        paths = [artifact, *[root / p for p in input_relatives(entry["node_id"]) if (root / p).is_file()]]
        if candidate:
            from ..workflows.review_audit import _source_bundle
            if _source_bundle(root, [p for p in paths if p.resolve() != artifact.resolve()])[0] != repair['input_hash']:
                raise ValueError('Specialist inputs changed after interrupted authoring; reassess before review')
        review, response = await _review_entry(root, checked, paths, expected)
        if not dependency_review_valid(root, review, expected, artifact):
            if not response.get('issues') or response.get('valid') is not False:
                raise ValueError('Specialist remains invalid after bounded review: ' + entry['id'] + ': ' + json.dumps(response))
            from .specialist_targeted_repair import repair_specialist_document, next_specialist_attempt
            if candidate:
                next_specialist_attempt(ctx, record, entry, response)
            candidate = await repair_specialist_document(ctx, record, candidate or entry, paths, response['issues'], service)
            review, response = await _review_entry(root, candidate, paths, expected)
            if not dependency_review_valid(root, review, expected, artifact):
                next_specialist_attempt(ctx, record, entry, response)
                candidate = await repair_specialist_document(ctx, record, candidate, paths, response['issues'], service)
                review, response = await _review_entry(root, candidate, paths, expected)
                if not dependency_review_valid(root, review, expected, artifact):
                    raise ValueError('Specialist remains invalid after two verified content attempts: ' + entry['id'] + ': ' + json.dumps(response))
        if candidate:
            entry.update(candidate)
        entry["dependency_review"] = review
        entry["previous_input_digest"] = entry["input_digest"]
        entry["input_digest"] = expected
        service._atomic_write(service.plan_path(root, ctx.run.id), payload)
        if candidate:
            from ..workflows.report_revision_store import save_report
            record['specialist_repairs'][entry['id']].update(status='accepted', review=review)
            save_report(ctx.run_state, record)


async def _review_entry(root: Path, entry: dict, paths: list[Path], expected: str) -> tuple[dict, dict]:
    from .api_visual_reviewer import api_visual_reviewer
    from ..workflows.review_audit import _source_bundle
    digest, paths = _source_bundle(root, paths)
    result = await api_visual_reviewer.invoke(project_path=str(root), purpose="specialist-dependency-review",
        prompt="Independently check whether the existing specialist document is fully consistent with "
        "the included CURRENT accepted research contracts. Check mathematical formulas, citation identity, "
        "assumptions, claims and limitations. A repair may correct a document transcription, but cannot "
        "redefine the accepted hypothesis, method or estimand. valid=true only when no revision is needed. "
        "Uncertainty or an unauthorized scientific change means valid=false. Output: " + entry['artifact'],
        schema={"type": "object", "required": ["valid", "issues"], "properties": {
            "valid": {"type": "boolean"}, "issues": {"type": "array", "items": {"type": "string"}}}},
        evidence_paths=paths, evidence_bundle_sha256=digest)
    review = {"input_digest": expected, "artifact_sha256": entry['artifact_sha256'],
        "trace_path": result.trace_path, "invocation_id": result.invocation_id,
        "paths": [p.relative_to(root).as_posix() for p in paths]}
    return review, json.loads(result.text)
