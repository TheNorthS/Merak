"""Independent semantic impact review over immutable before/after repair evidence."""

import hashlib
import json
from pathlib import Path

from ..utils.atomic_write import atomic_write_json


def source_fingerprints(root: Path) -> dict[str, str]:
    from .review_audit import audit_source_bundle
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in audit_source_bundle(root)[1]
            if not p.is_relative_to(root / '.merak/citation-source-evidence')}


def capture_before(root: Path, record: dict) -> None:
    directory = root / ".merak/report-revisions" / record["id"] / str(record["round"])
    path = directory / "before.json"
    if path.exists():
        raise ValueError("Repair evidence already exists without a completed journal write; reassess before retrying")
    payload = {p: (root / p).read_text(encoding="utf-8-sig") for p in record["targets"]}
    atomic_write_json(path, payload)
    record["before_path"] = path.relative_to(root).as_posix()
    record["before_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    record["sources_before"] = source_fingerprints(root)


def verify_unchanged_science(root: Path, record: dict) -> None:
    if record.get('comment_only_targets'):
        before = json.loads((root / record['before_path']).read_bytes())
        for target in record['comment_only_targets']:
            old = [line for line in before[target].splitlines() if not line.lstrip().startswith('%')]
            current = [line for line in (root / target).read_text(encoding='utf-8-sig').splitlines()
                       if not line.lstrip().startswith('%')]
            if old != current:
                raise ValueError('Comment-only repair changed bibliography entries: ' + target)
    current = source_fingerprints(root)
    old = record["sources_before"]
    changed = {p for p in set(current) | set(old) if current.get(p) != old.get(p)}
    if changed - set(record["targets"]):
        raise ValueError("Unrelated scientific inputs changed during local repair: " + ", ".join(sorted(changed - set(record["targets"]))))


async def assess_impact(root: Path, record: dict, activity) -> dict:
    from ..services.api_visual_reviewer import api_visual_reviewer
    from .review_audit import _source_bundle, REVIEW_MODEL_CALL_TIMEOUT_SECONDS

    verify_unchanged_science(root, record)
    before = root / record["before_path"]
    if hashlib.sha256(before.read_bytes()).hexdigest() != record["before_sha256"]:
        raise ValueError("Original repair evidence changed")
    packet = before.with_name("impact-input.json")
    atomic_write_json(packet, {"findings": record["groups"], "before": json.loads(before.read_bytes()),
        "after": {p: (root / p).read_text(encoding="utf-8-sig") for p in record["targets"]}})
    paths = [packet, *[root / p for p in ("ideas/SELECTED_IDEA.json", "experiments/METHOD_CONTRACT.json",
        "experiments/results/analysis.md", "NARRATIVE_REPORT.md", "experiments/results/accepted_matrix.json",
        ".merak/quality/independent-matrix-audit.json") if (root / p).is_file()]]
    from ..services.citation_source_evidence import retrieve_citation_evidence
    paths.extend(await retrieve_citation_evidence(root, record['groups'], activity))
    digest, paths = _source_bundle(root, paths)
    schema = {"type": "object", "required": ["scope", "reason", "unresolved"], "properties": {
        "scope": {"type": "string", "enum": ["local", "linked", "research", "uncertain"]},
        "reason": {"type": "string", "minLength": 1},
        "unresolved": {"type": "array", "items": {"type": "string"}}}, "additionalProperties": False}
    result = await api_visual_reviewer.invoke(project_path=str(root), purpose="report-revision-impact",
        prompt="Independently assess BEFORE and AFTER source edits against the original findings. "
        "Never infer scientific equivalence merely from a filename or the author's claim. "
        "local: publication metadata, wording or presentation with unchanged scientific meaning and source identity. "
        "linked: manuscript interpretation or numerical explanation needs linked claim/citation checks but the "
        "research question, selected method, data, computation and metrics remain unchanged. "
        "research: method/data/estimand/central evidence or hypothesis must change. "
        "uncertain: insufficient evidence to bound effects. Check changed bibliography titles, identifiers and notes "
        "for source replacement, retraction or changed claim support. List every unresolved original finding. "
        "Publisher-deposited Crossref records can verify DOI, authors, title, publication type and container "
        "metadata; they do not prove access to the publisher web page or full text. Judge only fields actually "
        "present, distinguish a bibliographic metadata check from a claim of full-text review, and retain "
        "any inaccurate source-access assertion as an issue. "
        "A finding is an allegation, not ground truth. Compare it against retrieved source excerpts, "
        "especially the exact official publication version; do not correct an unusual spelling by intuition. "
        "Unchanged bytes are acceptable if authoritative evidence disproves the allegation. Do not require "
        "edits to generated bibliography copies: the producer synchronizes them after this impact check. "
        "This is impact review, never final scientific acceptance; independent final review and audit still follow.",
        schema=schema, evidence_paths=paths, evidence_bundle_sha256=digest,
        timeout_seconds=REVIEW_MODEL_CALL_TIMEOUT_SECONDS, on_activity=activity)
    verify_unchanged_science(root, record)
    from .report_revision_store import require_expected
    require_expected(root, record)
    return {**json.loads(result.text), "trace_path": result.trace_path, "invocation_id": result.invocation_id,
            "model_identity": result.model_identity, "source_hash": digest}
