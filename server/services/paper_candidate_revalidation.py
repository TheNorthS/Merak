"""Revalidate saved author candidates before spending another model or repair budget."""

import hashlib
import json
from pathlib import Path

from .paper_candidate_transaction import PaperCandidate
from ..utils.atomic_write import atomic_write_bytes


def _science_inputs(value: str) -> dict:
    payload = json.loads(value)
    if not isinstance(payload, dict) or set(payload) != {"authoring", "upstream", "validator"}:
        raise ValueError("Unsupported paper candidate input contract")
    return {key: payload[key] for key in ("authoring", "upstream")}


def _saved_candidate(root: Path, stage: str, baseline: dict, inputs: str) -> tuple[Path, dict] | None:
    directory = root / ".merak/paper-candidates"
    receipts = sorted(directory.glob("*/transaction.json"), key=lambda path: path.stat().st_mtime_ns, reverse=True)
    for receipt in receipts:
        data = json.loads(receipt.read_bytes())
        identity = data.get("identity", {})
        if identity.get("stage") != stage or data.get("status") not in {"authoring", "interrupted", "rejected"}:
            continue
        if identity.get("baseline") != baseline or _science_inputs(identity["input_id"]) != _science_inputs(inputs):
            continue
        outputs = {}
        for relative in baseline:
            path = (receipt.parent / "candidate" / relative).resolve()
            if not path.is_relative_to((receipt.parent / "candidate/paper").resolve()) or not path.is_file():
                break
            raw = path.read_bytes()
            if not raw.strip() or hashlib.sha256(raw).hexdigest() != data.get("candidate_sha256", {}).get(relative):
                break
            outputs[relative] = raw
        if len(outputs) == len(baseline):
            return receipt, outputs
    return None


def revalidate_saved_candidate(coordinator, run) -> bool:
    if run.stage_id == "consistency" or not run.prior_attempts:
        return False
    service, paths = coordinator.service, coordinator.paths

    def inputs():
        return json.dumps({"authoring": service.authoring_input_hashes(coordinator.project_path),
            "upstream": service.stage_input_signature(paths, run.stage_id),
            "validator": service.stage_validator_signature(run.stage_id)}, sort_keys=True)

    targets = service.stage_outputs(paths, run.stage_id)
    root = paths["root"].resolve()
    baseline = {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                if path.is_file() else "<missing>" for path in targets}
    saved = _saved_candidate(root, run.stage_id, baseline, inputs())
    if not saved:
        return False
    receipt, outputs = saved
    previous_inputs = json.loads(json.loads(receipt.read_bytes())["identity"]["input_id"])
    if getattr(run, "revision_issues", None) and previous_inputs["validator"] == service.stage_validator_signature(run.stage_id):
        return False  # New reviewer/operator instructions still require their bounded author.
    candidate = PaperCandidate(root, run.stage_id, targets, inputs)
    with candidate:
        for relative, raw in outputs.items():
            atomic_write_bytes(candidate.files[(root / relative).resolve()], raw)
        review = service.validate_stage(coordinator.project_path, run.stage_id)
    candidate.publish(review)
    run.review = review
    if not review.get("passed"):
        return False
    service.record_review(paths, run.stage_id, review, run.prior_attempts)
    service.mark_stage(paths, run.stage_id, "completed", attempt=run.prior_attempts, review=review)
    return True
