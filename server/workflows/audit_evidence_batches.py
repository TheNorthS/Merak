"""Partition full audit inputs; preserve every partial verdict in independent synthesis."""

import json
import time
import uuid
from pathlib import Path
from typing import Any

from ..utils.atomic_write import atomic_write_json
from .draft_audit_evidence import MAX_DRAFT_AUDIT_BYTES


def evidence_batches(paths: list[Path]) -> list[list[Path]]:
    """Repeat manuscript context, cover every selected file, never truncate a file."""
    mandatory = [p for p in paths if p.suffix == '.bib' or p.name in {
        'independent-matrix-audit.json', 'accepted_matrix.json'} or '.merak/citation-source-evidence/' in p.as_posix()]
    context = [p for p in paths if p in mandatory or p.suffix == ".tex" or p.name in {"SELECTED_IDEA.json", "METHOD_CONTRACT.json"}]
    context_size = sum(p.stat().st_size for p in context)
    if context_size > MAX_DRAFT_AUDIT_BYTES // 2:
        context, context_size = mandatory, sum(p.stat().st_size for p in mandatory)
    batches, current, size = [], list(context), context_size
    for path in paths:
        if path in context:
            continue
        cost = 0 if path.suffix.casefold() in {".pdf", ".png", ".svg"} else path.stat().st_size
        if cost + context_size > MAX_DRAFT_AUDIT_BYTES:
            raise ValueError(f"Audit file requires explicit section splitting before review: {path.name}")
        if size + cost > MAX_DRAFT_AUDIT_BYTES or len(current) >= 160:
            batches.append(current)
            current, size = list(context), context_size
        current.append(path)
        size += cost
    if current:
        batches.append(current)
    return batches


async def invoke_batched_audit(*, reviewer: Any, project_path: str, skill: str,
                               prompt: str, schema: dict, paths: list[Path],
                               source_hash: str, timeout: float, activity: Any) -> Any:
    """One shared time budget; incomplete or source-changing batches cannot be accepted."""
    from .review_audit import _source_bundle
    from .audit_batch_receipts import receipt_record, verify_batch_receipt

    root = Path(project_path).resolve()
    groups = evidence_batches(paths)
    if len(groups) <= 1:
        return await reviewer.invoke(project_path=project_path, prompt=prompt, purpose=f"audit-{skill}",
            schema=schema, evidence_paths=paths, evidence_bundle_sha256=source_hash,
            timeout_seconds=timeout, on_activity=activity)
    started = time.monotonic()
    from .audit_batch_checkpoint import batch_checkpoint, load_batch, save_batch
    checkpoint = batch_checkpoint(root, skill, prompt, schema, source_hash)
    directory = root / ".merak/audit-batches" / uuid.uuid4().hex
    directory.mkdir(parents=True)
    records, summaries, models = [], [], set()
    for index, group in enumerate(groups):
        remaining = timeout - (time.monotonic() - started)
        if remaining <= 0:
            raise TimeoutError("Partitioned audit exhausted its shared model time budget")
        digest, group = _source_bundle(root, group)
        purpose = f"audit-{skill}-part-{index + 1}"
        result = load_batch(checkpoint, root, index + 1, purpose, digest)
        if result is None:
            result = await reviewer.invoke(project_path=project_path,
                prompt=prompt + f"\nPartial audit batch {index + 1}/{len(groups)}. Review only included files. "
                "Preserve concrete blockers verbatim. Report unresolved cross-file questions and evidence locations; "
                "do not claim complete project coverage or treat files in other batches as missing.",
                purpose=purpose, schema=schema, evidence_paths=group,
                evidence_bundle_sha256=digest, timeout_seconds=remaining, on_activity=activity)
            save_batch(checkpoint, root, index + 1, purpose, digest, result)
        models.add(result.model_identity)
        summary = directory / f"part-{index + 1}.json"
        atomic_write_json(summary, {"batch": index + 1, "source_bundle_sha256": digest,
            "paths": [p.relative_to(root).as_posix() for p in group], "review": json.loads(result.text)})
        summaries.append(summary)
        records.append(receipt_record(root, result, group, summary, skill, index + 1))
    if _source_bundle(root, paths)[0] != source_hash or len(models) != 1:
        raise ValueError("Audit inputs or reviewer identity changed between evidence batches")
    remaining = timeout - (time.monotonic() - started)
    if remaining <= 0:
        raise TimeoutError("Partitioned audit has no synthesis budget remaining")
    digest, summaries = _source_bundle(root, summaries)
    if sum(p.stat().st_size for p in summaries) > MAX_DRAFT_AUDIT_BYTES:
        raise ValueError("Audit partial reports exceed the synthesis budget; no findings may be truncated")
    final = await reviewer.invoke(project_path=project_path, purpose=f"audit-{skill}", schema=schema,
        evidence_paths=summaries, evidence_bundle_sha256=digest, timeout_seconds=remaining, on_activity=activity,
        prompt=prompt + "\nSynthesize the attached independent partial audits. You are reading their reports, "
        "not all original files. Preserve ALL draft_blockers verbatim and all material limitations. "
        "If any batch is ERROR/BLOCKED, preserve that verdict. Do not upgrade FAIL or WARN. "
        "Disclose distributed coverage and unresolved cross-file questions. Never claim a single exhaustive read.")
    manifest = {"schema": 1, "source_hash": source_hash, "skill": skill,
        "paths": [p.relative_to(root).as_posix() for p in paths], "parts": records,
        "model_identity": final.model_identity}
    atomic_write_json(Path(final.trace_path) / "audit-batches.json", manifest)
    verify_batch_receipt(root, Path(final.trace_path), source_hash)
    return final
