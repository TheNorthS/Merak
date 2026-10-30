"""Reuse already authored paper plans without generating replacements on errors."""
import json
from pathlib import Path
from .paper_plan_asset_links import plan_link_issues


def require_current_model_plan(root: Path) -> None:
    """A downstream consumer can reject a stale plan but cannot replace its producer."""
    from .paper_plan import paper_plan_service
    from ..contracts.preparation import PreparationContractError

    if paper_plan_service.is_valid(paper_plan_service.path(root)) and paper_plan_service.is_current(root) and not plan_link_issues(root):
        build = json.loads((root / paper_plan_service.build_relative_path).read_text(encoding="utf-8-sig"))
        if not str(build.get("generator") or "").startswith("deterministic:"):
            return
    raise PreparationContractError("Model-authored paper plan is missing or stale; resume narrative producer",
                                   owner="narrative", paths=("paper/PAPER_PLAN.md",))


async def reuse_current_plan(host, node, run, service) -> bool:
    from .skill_orchestrator import skill_orchestrator
    root = Path(run.project_path).resolve()
    path = service.path(root)
    if not service.is_valid(path) or not service.is_current(root) or plan_link_issues(root):
        return False
    build = json.loads((root / service.build_relative_path).read_text(encoding="utf-8-sig"))
    if str(build.get("generator") or "").startswith("deterministic:"):
        return False
    else:
        skill_orchestrator.mark_execution(run.project_path, run.id, node.id, "paper-plan", "reused",
                                         role="delegate", output=path.read_text(encoding="utf-8"),
                                         policy_loaded=False, execution_kind="model_owned")
        await host._emit(run, "skill_invocation_reused", {"node_id": node.id, "skill": "paper-plan",
                                                         "role": "delegate", "artifact": str(path)})
    return True
