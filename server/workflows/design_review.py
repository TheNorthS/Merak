"""Finish read-only code review before accepting implementation or producing evidence."""
from pathlib import Path
from typing import Any

from ..contracts.preparation import PreparationContractError
from ..services.implementation_review_receipt import REVIEW_POLICY, load_review, persist_review, review_source_hash
from ..services.training_review_policy import current_review_findings, review_blocks


class ImplementationReviewBlocked(PreparationContractError):
    def __init__(self, assessment: dict, opts: dict):
        self.findings = [{**item, "category": "implementation_review", "owner_node": "exp-design", "upstream_node": "exp-design"}
                         for item in current_review_findings(assessment, opts)]
        super().__init__(str(assessment.get("summary") or "Implementation review blocked"))

    def details(self) -> dict:
        details = super().details()
        if self.findings:
            # The report summary is context, not an extra unowned quality defect.
            # Preserve exact messages so diagnostic normalization deduplicates
            # them against the typed owner findings instead of widening repair.
            details["issues"] = [str(item.get("message") or item.get("plain_message") or "")
                                 for item in self.findings]
        return {**details, "node_risk_audit": {"passed": False, "findings": self.findings}}

    def finding(self) -> dict:
        return self.findings[0] if self.findings else super().finding()


async def ensure_design_review(host: Any, run: Any, direction: str, opts: dict, assurance: str) -> dict:
    if opts.get("code_review", True) is False:
        return {}
    root = Path(run.project_path).resolve()
    source_hash = review_source_hash(root)
    receipt = load_review(root)
    assessment = receipt.get("assessment", {})
    if receipt.get("source_sha256") != source_hash or receipt.get("review_policy") != REVIEW_POLICY:
        await host._emit(run, "code_review_started", {"node_id": "exp-design"})
        raw = await host._run_code_review(run, direction, str(opts.get("effort") or "balanced"), assurance)
        assessment = host._parse_training_check_result(raw, assurance=assurance)
        if review_source_hash(root) != source_hash:
            raise RuntimeError("Implementation sources changed during read-only review; retry from a stable snapshot")
        host._persist_training_check(run, assessment, raw)
        persist_review(root, source_hash, assessment)
        await host._emit(run, "code_review_completed", {"node_id": "exp-design", "verdict": assessment.get("verdict"),
                          "blocking": review_blocks(assessment, opts), "result": assessment.get("summary"),
                          "findings": current_review_findings(assessment, opts)})
    opts["_training_check"] = assessment
    run.options["_training_check"] = assessment
    if review_blocks(assessment, opts):
        raise ImplementationReviewBlocked(assessment, opts)
    return assessment
