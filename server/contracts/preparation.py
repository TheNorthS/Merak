"""Typed source-contract defects route to their producer without fabricating completion."""
import hashlib


class PreparationContractError(ValueError):
    def __init__(self, message: str, *, owner: str = "exp-design", paths: tuple[str, ...] = ()):
        super().__init__(message)
        self.owner = owner
        self.paths = paths or ("experiments/configs/main.yaml", "experiments/RUN_SPEC.json")

    def finding(self) -> dict:
        identity = hashlib.sha256(str(self).encode()).hexdigest()[:12]
        return {"id": f"PREPARATION-{identity}", "severity": "blocker", "category": "artifact_contract",
                "owner_node": self.owner, "upstream_node": self.owner, "message": str(self),
                "plain_message": str(self), "target_files": list(self.paths), "evidence": list(self.paths),
                "remediation": "Repair the producer's declared contract; preserve scientific scope and revalidate."}

    def details(self) -> dict:
        return {"issues": [str(self)], "review_findings": [self.finding()],
                "node_risk_audit": {"passed": False, "findings": [self.finding()]},
                "preparation_phase": "source_contract", "recoverable": True}
