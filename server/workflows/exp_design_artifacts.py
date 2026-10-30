"""Verify authored design; missing scientific artifacts are never synthesized."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..contracts.preparation import PreparationContractError
from ..services.method_contract import method_contract_service
from .models import WorkflowRun


DESIGN_OUTPUTS = (
    "experiments/EXPERIMENT_PLAN.md", "experiments/METHOD_CONTRACT.json",
    "experiments/RUN_SPEC.json", "experiments/configs/main.yaml",
    "experiments/IMPLEMENTATION_BLUEPRINT.json",
)


async def ensure_exp_design_artifacts(
    host: Any, run: WorkflowRun, result: str, research_direction: str, assurance: str,
) -> None:
    root = Path(run.project_path)
    missing = [relative for relative in DESIGN_OUTPUTS
               if not (root / relative).is_file() or not (root / relative).stat().st_size]
    if missing:
        raise PreparationContractError(
            "Model-authored experiment design is incomplete; resume the producer. Missing: " + ", ".join(missing),
            paths=tuple(missing),
        )
    for relative in DESIGN_OUTPUTS:
        if not relative.endswith(".json"):
            continue
        try:
            content = json.loads((root / relative).read_text(encoding="utf-8-sig"))
            if not isinstance(content, dict):
                raise ValueError("expected a JSON object")
        except (ValueError, UnicodeError) as error:
            raise PreparationContractError(f"Invalid authored design {relative}: {error}", paths=(relative,)) from error
    # Hashes remain runtime-owned; no scientific defaults or generated plans.
    method_contract_service.stamp_method_contract_idea_hash(root)
    await host._emit(run, "node_artifact_canonicalized", {
        "node_id": "exp-design", "from": "model-authored design",
        "to": str(root / "experiments"), "generated_source_code": False,
    })
