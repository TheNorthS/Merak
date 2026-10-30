"""No evidence generation until the implementation and its configured review are current."""
from pathlib import Path
import json

from ..contracts.preparation import PreparationContractError
from ..services.experiment_implementation import experiment_implementation_service
from ..services.implementation_review_receipt import load_review, review_source_hash
from ..services.training_review_policy import review_blocks


def require_evidence_producer_ready(project_path: str, options: dict) -> None:
    root = Path(project_path).resolve()
    method_path = root / "experiments/METHOD_CONTRACT.json"
    method = json.loads(method_path.read_text(encoding="utf-8-sig")) if method_path.is_file() else {}
    if method.get("status") not in {"implemented", "ready", "complete"}:
        raise PreparationContractError("Evidence producer requires a finalized implementation contract")
    report = experiment_implementation_service.audit(root)
    if report.get("blocking"):
        messages = [str(item.get("message")) for item in report.get("findings", [])]
        raise PreparationContractError("Evidence producer requires valid implementation: " + "; ".join(messages[:8]))
    if options.get("code_review", True) is False:
        return
    receipt = load_review(root)
    if receipt.get("source_sha256") != review_source_hash(root) or review_blocks(receipt.get("assessment", {}), options):
        raise PreparationContractError("Evidence producer requires a current passing implementation review before generation")
