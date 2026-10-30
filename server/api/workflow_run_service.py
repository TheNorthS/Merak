"""Application service that validates and normalizes workflow run requests."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..services.research_intake import research_intake_service
from ..services.workflow_inputs import workflow_input_service
from ..services.workflow_readiness import validate_submission_start
from . import settings as settings_api
from . import ssh as ssh_api


class WorkflowRequestError(ValueError):
    """A request is structurally valid JSON but cannot safely start a run."""

    def __init__(self, detail: Any) -> None:
        super().__init__(str(detail))
        self.detail = detail


@dataclass(frozen=True)
class PreparedWorkflowRun:
    options: dict[str, Any]


def _validate_research_inputs(request: Any) -> None:
    issues = research_intake_service.validate_inputs(
        request.research_mode,
        request.ref_paper,
        request.base_repo,
    )
    _, workflow_issues = workflow_input_service.resolve(
        request.project_path,
        request.input_files,
    )
    issues.extend(workflow_issues)
    if issues:
        raise WorkflowRequestError({"issues": issues})


def _execution_context(request: Any) -> tuple[bool, str, str, bool]:
    enabled = bool(request.run_experiment and "exp-run" in request.node_ids)
    gpu_target = request.gpu_target if enabled else "none"
    ssh_server_id = (
        request.ssh_server_id
        if enabled and gpu_target == "remote"
        else ""
    )
    return enabled, gpu_target, ssh_server_id, bool(request.wandb and enabled)


def _validate_execution_target(
    *,
    enabled: bool,
    gpu_target: str,
    ssh_server_id: str,
) -> None:
    if not enabled:
        return
    if gpu_target == "remote":
        if not ssh_server_id:
            raise WorkflowRequestError("远程实验必须选择已验证的 SSH 服务器")
        if not ssh_api.is_ssh_server_verified(ssh_server_id):
            raise WorkflowRequestError("所选 SSH 服务器未配置、配置已变更或尚未通过连接测试")
    elif gpu_target in {"vast", "modal"}:
        integration = "vastai" if gpu_target == "vast" else "modal"
        if not settings_api.is_integration_verified(integration):
            raise WorkflowRequestError(f"{gpu_target} 未配置或尚未通过连接测试")


def _enabled_integrations(request: Any) -> dict[str, bool]:
    requested = {
        "gemini": request.enable_gemini,
        "gpt_image": request.enable_gpt_image,
        "zotero": request.enable_zotero,
        "obsidian": request.enable_obsidian,
        "patent": request.enable_patent_search,
    }
    return {
        name: bool(enabled and settings_api.is_integration_verified(name))
        for name, enabled in requested.items()
    }


def _validate_integrations(request: Any, enabled: dict[str, bool]) -> None:
    if "web" in request.literature_sources and not settings_api.is_integration_verified("exa"):
        raise WorkflowRequestError("Web 已被选作文献来源，但 Exa 未配置或尚未通过连接测试；请配置 Exa 或取消选择 Web")
    labels = {"gemini": "Gemini", "zotero": "Zotero", "obsidian": "Obsidian"}
    requested = {
        "gemini": request.enable_gemini,
        "zotero": request.enable_zotero,
        "obsidian": request.enable_obsidian,
    }
    for source in set(request.literature_sources).intersection(labels):
        if not requested[source]:
            raise WorkflowRequestError(
                f"{labels[source]} 已被选作文献来源，但对应集成开关未启用"
            )
        if not enabled[source]:
            raise WorkflowRequestError(
                f"{labels[source]} 已被选作文献来源，但配置尚未通过连接测试"
            )
    if request.enable_patent_search and not enabled["patent"]:
        raise WorkflowRequestError("专利检索已启用，但 SerpAPI/EPO OPS 未配置或尚未通过连接测试")
    if request.enable_zotero and not enabled["zotero"]:
        raise WorkflowRequestError("Zotero 已启用，但当前配置尚未通过连接测试")
    if request.enable_obsidian and not enabled["obsidian"]:
        raise WorkflowRequestError("Obsidian 已启用，但当前 Vault 尚未通过访问测试")


def _validate_overleaf(request: Any) -> None:
    if not request.enable_overleaf_sync:
        return
    from ..services.overleaf_sync import overleaf_sync

    if "compile" not in request.node_ids:
        raise WorkflowRequestError("Overleaf 工作流同步要求选择“编译 PDF”节点")
    if not request.overleaf_project_id:
        raise WorkflowRequestError("Overleaf 同步已启用，但未选择关联项目")
    if not overleaf_sync.is_ready_for_project(
        request.overleaf_project_id,
        request.project_path,
    ):
        raise WorkflowRequestError(
            "Overleaf 项目未关联到当前项目的 paper 目录、凭据不可用或后端重启后需要重新关联"
        )


def _research_strategy(request: Any) -> dict[str, Any]:
    return {
        "literature_year_from": request.literature_year_from,
        "literature_year_to": request.literature_year_to,
        "literature_max_papers": request.literature_max_papers,
        "literature_sources": request.literature_sources,
        "literature_venues": request.literature_venues,
        "include_keywords": request.include_keywords,
        "exclude_keywords": request.exclude_keywords,
        "seed_papers": request.seed_papers,
        "evidence_policy": request.evidence_policy,
        "novelty_window_years": request.novelty_window_years,
    }


def _pipeline_options(
    request: Any,
    *,
    execution_enabled: bool,
    gpu_target: str,
    ssh_server_id: str,
    wandb_enabled: bool,
    integrations: dict[str, bool],
) -> dict[str, Any]:
    excluded = {
        "node_ids", "project_path", "research_direction", "effort", "assurance",
        "gpu_target", "ssh_server_id", "run_experiment", "wandb",
        "literature_year_from", "literature_year_to", "literature_max_papers",
        "literature_sources", "literature_venues", "include_keywords",
        "exclude_keywords", "seed_papers", "evidence_policy",
        "novelty_window_years", "enable_gemini", "enable_gpt_image",
        "enable_zotero", "enable_obsidian", "enable_patent_search",
    }
    options = {
        key: value
        for key, value in request.model_dump().items()
        if key not in excluded
    }
    options.update({
        "gpu_target": gpu_target,
        "ssh_server_id": ssh_server_id,
        "run_experiment": execution_enabled,
        "wandb": wandb_enabled,
        "illustration_mode": "auto",
        "research_strategy": _research_strategy(request),
        "enable_gemini": integrations["gemini"],
        "enable_gpt_image": integrations["gpt_image"],
        "enable_zotero": integrations["zotero"],
        "enable_obsidian": integrations["obsidian"],
        "enable_patent_search": integrations["patent"],
    })
    return options


def prepare_workflow_run(request: Any) -> PreparedWorkflowRun:
    _validate_research_inputs(request)
    execution_enabled, gpu_target, ssh_server_id, wandb_enabled = (
        _execution_context(request)
    )
    submission_issues = validate_submission_start(
        request.node_ids,
        request.assurance,
        {
            "run_experiment": execution_enabled,
            "non_experiment_evidence_mode": request.non_experiment_evidence_mode,
        },
    )
    if submission_issues:
        raise WorkflowRequestError({"issues": submission_issues})
    _validate_execution_target(
        enabled=execution_enabled,
        gpu_target=gpu_target,
        ssh_server_id=ssh_server_id,
    )
    integrations = _enabled_integrations(request)
    _validate_integrations(request, integrations)
    _validate_overleaf(request)
    return PreparedWorkflowRun(options=_pipeline_options(
        request,
        execution_enabled=execution_enabled,
        gpu_target=gpu_target,
        ssh_server_id=ssh_server_id,
        wandb_enabled=wandb_enabled,
        integrations=integrations,
    ))
