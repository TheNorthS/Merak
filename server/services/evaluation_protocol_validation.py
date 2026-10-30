"""Read-only early validation of the exact protocol consumed by publication."""
import json
from pathlib import Path
import yaml

from ..contracts.preparation import PreparationContractError


def validate_project_evaluation(root: Path) -> dict:
    from .evaluation_protocol_projection import project_evaluation_protocol
    run_path, config_path = root / "experiments/RUN_SPEC.json", root / "experiments/configs/main.yaml"
    try:
        run = json.loads(run_path.read_text(encoding="utf-8-sig")) if run_path.is_file() else {}
        config = yaml.safe_load(config_path.read_text(encoding="utf-8-sig")) if config_path.is_file() else {}
        plan = root / "experiments/EXPERIMENT_PLAN.md"
        return project_evaluation_protocol(run, config, plan_bytes=plan.read_bytes() if plan.is_file() else None)
    except (OSError, ValueError, yaml.YAMLError) as error:
        if isinstance(error, PreparationContractError):
            raise
        raise PreparationContractError(f"Evaluation protocol cannot be read: {error}") from error


def evaluation_contract_findings(root: Path) -> list[dict]:
    try:
        validate_project_evaluation(root)
    except PreparationContractError as error:
        return [error.finding()]
    return []
