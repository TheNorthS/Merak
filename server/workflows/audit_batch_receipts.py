"""Validate distributed audit coverage, raw model receipts and unwaived blocking findings."""

import hashlib
import json
from pathlib import Path
from typing import Any


def _local(root: Path, relative: str) -> Path:
    path = (root / relative).resolve()
    if not path.is_relative_to(root):
        raise ValueError("Audit receipt escapes project")
    return path


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _json(path: Path) -> dict:
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise ValueError("Audit receipt must be an object")
    return value


def _trace(root: Path, directory: Path, purpose: str, model: str) -> tuple[dict, dict]:
    if not directory.resolve().is_relative_to(root / ".merak/model-api-reviewer"):
        raise ValueError("Audit trace is outside the native reviewer directory")
    meta, response = _json(directory / "meta.json"), _json(directory / "response.txt")
    if (meta.get("success") is not True or meta.get("purpose") != purpose
            or meta.get("model_identity") != model
            or meta.get("response_sha256") != _sha(directory / "response.txt")
            or not isinstance(response.get("draft_blockers"), list)
            or meta.get("evidence_packet", {}).get("truncated_paths")):
        raise ValueError("Audit batch native receipt is invalid")
    return meta, response


def receipt_record(root: Path, result: Any, paths: list[Path], summary: Path, skill: str, index: int) -> dict:
    directory = Path(result.trace_path).resolve()
    _trace(root, directory, f"audit-{skill}-part-{index}", result.model_identity)
    return {"trace": directory.relative_to(root).as_posix(),
        "invocation_id": result.invocation_id,
        "summary": summary.relative_to(root).as_posix(), "summary_sha256": _sha(summary),
        "paths": [p.relative_to(root).as_posix() for p in paths],
        "meta_sha256": _sha(directory / "meta.json"), "response_sha256": _sha(directory / "response.txt")}


def verify_batch_receipt(root: Path, directory: Path, expected_source: str) -> dict[str, str]:
    """Revalidate all source bytes and traces before accepting or reusing synthesis."""
    from .review_audit import _source_bundle

    root, directory = root.resolve(), directory.resolve()
    manifest_path = directory / "audit-batches.json"
    manifest = _json(manifest_path)
    paths = [_local(root, name) for name in manifest["paths"]]
    if manifest.get("schema") != 1 or manifest.get("source_hash") != expected_source:
        raise ValueError("Audit batch binding does not match selected sources")
    if _source_bundle(root, paths)[0] != expected_source:
        raise ValueError("Audit evidence changed after batch review")
    model, skill = manifest["model_identity"], manifest["skill"]
    final_meta, final = _trace(root, directory, f"audit-{skill}", model)
    covered, blockers, verdicts, summaries = set(), [], [], []
    hashes = {"audit-batches.json": _sha(manifest_path)}
    for index, record in enumerate(manifest["parts"], 1):
        trace, summary = _local(root, record["trace"]), _local(root, record["summary"])
        meta, response = _trace(root, trace, f"audit-{skill}-part-{index}", model)
        for name, path in (("meta", trace / "meta.json"), ("response", trace / "response.txt"), ("summary", summary)):
            digest = _sha(path)
            if digest != record[f"{name}_sha256"]:
                raise ValueError("Audit batch trace or summary was modified")
            hashes[f"part-{index}-{name}"] = digest
        batch = [_local(root, name) for name in record["paths"]]
        if (meta.get("invocation_id") != record["invocation_id"]
                or meta.get("evidence_packet", {}).get("source_bundle_sha256") != _source_bundle(root, batch)[0]
                or _json(summary).get("review") != response):
            raise ValueError("Audit batch does not bind its complete source and response")
        covered.update(record["paths"])
        blockers.extend(response["draft_blockers"])
        verdicts.append(response.get("verdict"))
        summaries.append(summary)
    if covered != set(manifest["paths"]) or not verdicts:
        raise ValueError("Audit batches have incomplete source coverage")
    if final_meta.get("evidence_packet", {}).get("source_bundle_sha256") != _source_bundle(root, summaries)[0]:
        raise ValueError("Audit synthesis is not bound to all partial reports")
    if any(item not in final["draft_blockers"] for item in blockers):
        raise ValueError("Audit synthesis omitted a partial audit blocker")
    if (("ERROR" in verdicts and final.get("verdict") != "ERROR")
            or ("BLOCKED" in verdicts and final.get("verdict") not in {"ERROR", "BLOCKED"})
            or ("FAIL" in verdicts and final.get("verdict") not in {"ERROR", "BLOCKED", "FAIL"})
            or ("WARN" in verdicts and final.get("verdict") in {"PASS", "NOT_APPLICABLE"})):
        raise ValueError("Audit synthesis upgraded an unresolved partial verdict")
    return hashes
