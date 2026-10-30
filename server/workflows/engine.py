"""
工作流执行引擎 — 将可视化节点图转为真实 Agent 任务链

功能：
- 节点拓扑排序（按依赖关系）
- 逐节点执行（Agent + 工具）
- 阶段门控（前置节点完成才执行后续）
- 可恢复状态持久化
- 实时状态推送
- 审计链集成
"""

import asyncio
import ast
import csv
import hashlib
import inspect
import json
import re
import shutil
import time
import uuid
from typing import Any, Optional, Callable
from pathlib import Path

import structlog

from ..agent.engine import agent_engine
from ..agent.prompts import SLASH_COMMANDS, MERAK_SYSTEM_PROMPT
from ..agent import ModelRole, model_router
from ..services.project_memory import project_memory
from ..services.simulation_policy import (
    FORBIDDEN_RENDERED_SIMULATION_LABELS,
    SIMULATION_MANIFEST_SCHEMA,
    SIMULATION_RENDERER_VERSION,
    rendered_mode_framing_hits_outside_end_disclosure,
    simulation_disclosure_report,
    simulation_manifest_contract_issues,
    strip_latex_comments,
    visible_watermark_commands,
)
from ..services.workflow_inputs import (
    artifact_state,
    artifact_state_equal,
    snapshot_paths,
    workflow_input_service,
)
from ..utils.atomic_write import atomic_write_json, atomic_write_text, path_lock
from .effort_config import build_effort_prompt_section, get_effort_config
from .session_state import SessionState
from .run_state import ProjectRunLease, RunState, TERMINAL_PHASE_STATES
from .revision_targets import (
    paper_revision_fallback_targets,
    revision_asset_ids,
    revision_target_files,
    stable_revision_finding_text,
)
from .revision_messages import humanize_revision_issue
from .resume_policy import (
    phase_failed_from_timeout,
    phase_is_durably_terminal,
    phase_requires_revalidation,
    resumable_phase_ids,
    tool_artifact_path,
    training_check_blocks_current_mode,
)
from .models import (
    AgentNodeWatchdogTimeout,
    NodeStatus,
    WorkflowNode,
    WorkflowRun,
)
from .review_audit import (
    BOUNDED_REVIEW_FALLBACK_EVIDENCE_MODES,
    MANAGED_REVIEW_ROUNDS_MAX,
    REVIEW_MODEL_CALL_TIMEOUT_SECONDS,
    REVIEW_NATIVE_IMAGE_LIMIT,
    Verdict,
    audit_chain,
)

logger = structlog.get_logger()
from .engine_lifecycle import LifecycleMixin
from .engine_revision import RevisionMixin
from .engine_execution import ExecutionMixin
from .engine_execution_extra import ExecutionExtraMixin
from .engine_inputs import InputsMixin
from .engine_artifacts_a import ArtifactsAMixin
from .engine_artifacts_b import ArtifactsBMixin
from .engine_artifacts_b_extra import ArtifactsBExtraMixin
from .engine_gates_a import GatesAMixin
from .engine_gates_b import GatesBMixin
from .engine_recovery import RecoveryMixin

from .workflow_policy import (
    DEFAULT_HUMAN_CHECKPOINT_NODES,
    REVISION_GATE_SIGNATURE_VERSION,
    WORKFLOW_TOOL_CONTRACT_VERSION,
    NODE_RUNTIME_CONTRACT_VERSIONS,
    AUTONOMOUS_REVISION_ROUNDS,
    MIN_AUTONOMOUS_REVISION_ROUNDS,
    MAX_AUTONOMOUS_REVISION_ROUNDS,
    MANAGED_EXPERIMENT_DIRECT_HASH_LIMIT_BYTES,
    MANAGED_EXPERIMENT_SNAPSHOT_MODE,
    SEMANTIC_RESULTS_SNAPSHOT_MODE,
    RISK_AUDIT_ACCEPTANCE_CACHE_VERSION,
    WORKFLOW_ILLUSTRATION_MODES,
    normalize_revision_rounds,
    normalize_workflow_illustration_mode,
    LITERATURE_SOURCE_TOOLS,
    LITERATURE_SEARCH_NODES,
    LITERATURE_FETCH_SOURCES,
    LITERATURE_SEARCH_ERROR_RE,
)
# Bump only the affected node when orchestration code changes its runtime
# acceptance/repair semantics.  Hashing this entire module for every node made
# an unrelated figure or resume fix invalidate all previously accepted phases.
# The UI may choose a bounded revision budget. The backend clamps it so a stale
# client cannot create an unbounded model-cost loop.







class WorkflowEngine(LifecycleMixin, RevisionMixin, ExecutionMixin, ExecutionExtraMixin, InputsMixin, ArtifactsAMixin, ArtifactsBMixin, ArtifactsBExtraMixin, GatesAMixin, GatesBMixin, RecoveryMixin):
    """工作流执行引擎"""

    RESUME_CLAIM_TTL_SECONDS = 120.0
    RESUME_CLAIM_HEARTBEAT_SECONDS = 30.0
    PROJECT_CLAIM_TTL_SECONDS = 120.0
    PROJECT_CLAIM_HEARTBEAT_SECONDS = 30.0


    async def _start_run(
        self,
        node_ids: list[str],
        project_path: str,
        research_direction: str = "",
        effort: str = "balanced",
        assurance: str = "draft",
        pipeline_options: Optional[dict] = None,
        on_event: Optional[Callable] = None,
    ) -> str:
        from .run_start_coordinator import start_run

        return await start_run(
            self, node_ids, project_path, research_direction, effort,
            assurance, pipeline_options, on_event,
        )

    async def _execute_run(
        self, run: WorkflowRun, research_direction: str,
        effort: str = "balanced", assurance: str = "draft",
        opts: Optional[dict] = None,
    ) -> None:
        from .run_execution_coordinator import execute_run

        await execute_run(self, run, research_direction, effort, assurance, opts)

    async def _prepare_node_for_gate(
        self,
        node: WorkflowNode,
        run: WorkflowRun,
        result: str,
        research_direction: str,
        assurance: str,
        opts: dict,
    ) -> str:
        from .node_gate_preparation import prepare_node_for_gate

        return await prepare_node_for_gate(
            self, node, run, result, research_direction, assurance, opts,
        )

    _revision_target_files = staticmethod(revision_target_files)

    _revision_asset_ids = staticmethod(revision_asset_ids)

    _stable_revision_finding_text = staticmethod(stable_revision_finding_text)

    _paper_revision_fallback_targets = staticmethod(
        paper_revision_fallback_targets
    )

    @classmethod
    def _gate_revision_diagnostics(cls, gate: dict) -> dict:
        from .revision_diagnostics import normalize_gate_diagnostics

        return normalize_gate_diagnostics(cls, gate)


    def _revision_owner_for_gate(
        self,
        current_node: WorkflowNode,
        run: WorkflowRun,
        gate: dict,
        owner_rounds: Optional[dict[str, int]] = None,
    ) -> WorkflowNode:
        from .revision_owner_policy import revision_owner_for_gate

        return revision_owner_for_gate(self, current_node, run, gate, owner_rounds)




    _humanize_revision_issue = staticmethod(humanize_revision_issue)














    async def _repair_failed_experiment_source(
        self,
        *,
        run: WorkflowRun,
        diagnostics: dict[str, Any],
        round_number: int,
        cycle: int,
    ) -> str:
        from .experiment_failure_repair import repair_failed_experiment_source

        return await repair_failed_experiment_source(
            self, run, diagnostics, round_number, cycle,
        )

    async def _revise_node_from_gate(
        self,
        node: WorkflowNode,
        run: WorkflowRun,
        diagnostics: dict,
        round_number: int,
        cycle: int,
        user_feedback: str,
        research_direction: str,
        effort: str,
        assurance: str,
        opts: dict,
    ) -> str:
        from .revision_execution import revise_node_from_gate

        return await revise_node_from_gate(
            self, node, run, diagnostics, round_number, cycle, user_feedback,
            research_direction, effort, assurance, opts,
        )

    async def _run_node_revision_loop(
        self, *, node: WorkflowNode, run: WorkflowRun, initial_result: str,
        research_direction: str, effort: str, assurance: str, opts: dict,
        require_fresh: bool, checkpoint_timeout: int, max_revision_rounds: int,
    ) -> tuple[dict, str]:
        from .revision_loop_coordinator import run_node_revision_loop

        return await run_node_revision_loop(
            self, node=node, run=run, initial_result=initial_result,
            research_direction=research_direction, effort=effort, assurance=assurance,
            opts=opts, require_fresh=require_fresh,
            checkpoint_timeout=checkpoint_timeout,
            max_revision_rounds=max_revision_rounds,
        )










    @staticmethod
    def _managed_experiment_output_issues(
        root: Path,
        run_spec: dict[str, Any],
        job: Any,
    ) -> list[str]:
        from .managed_output_validation import managed_output_issues

        return managed_output_issues(
            root, run_spec, job,
            direct_hash_limit=MANAGED_EXPERIMENT_DIRECT_HASH_LIMIT_BYTES,
        )


    async def _execute_managed_experiment(self, run: WorkflowRun, opts: dict) -> str:
        from .managed_experiment_execution import execute_managed_experiment

        return await execute_managed_experiment(self, run, opts)




    async def _execute_node(
        self, node: WorkflowNode, run: WorkflowRun, direction: str,
        effort: str, assurance: str, wandb: bool = False,
        compact: bool = False, gpu_target: str = "none",
        ssh_server_id: str = "", opts: Optional[dict] = None,
        revision_context: str = "",
    ) -> str:
        from .node_execution_coordinator import execute_node

        return await execute_node(
            self, node, run, direction, effort, assurance, wandb, compact,
            gpu_target, ssh_server_id, opts, revision_context,
        )





    async def _execute_staged_experiment_implementation(
        self, *, run: WorkflowRun, direction: str, opts: dict[str, Any],
    ) -> dict[str, Any]:
        from .staged_implementation_coordinator import execute_staged_implementation

        return await execute_staged_implementation(self, run, direction)




































    async def _execute_review_node(
        self,
        node: WorkflowNode,
        run: WorkflowRun,
        assurance: str,
        opts: dict[str, Any],
    ) -> str:
        from .review_execution import execute_review_node

        return await execute_review_node(self, node, run, assurance, opts)


    def _ensure_simulation_results_analysis(
        self,
        run: WorkflowRun,
        research_direction: str,
        result: str = "",
    ) -> str:
        from .simulation_result_analysis import ensure_simulation_results_analysis

        return ensure_simulation_results_analysis(
            self, run, research_direction, result,
        )


    async def _ensure_exp_design_artifacts(
        self,
        run: WorkflowRun,
        result: str,
        research_direction: str,
        assurance: str = "draft",
    ) -> None:
        from .exp_design_artifacts import ensure_exp_design_artifacts

        await ensure_exp_design_artifacts(
            self, run, result, research_direction, assurance,
        )

    @staticmethod
    def _build_exp_design_depth_supplement(
        selected: str,
        research_direction: str,
        selected_contract: Optional[dict[str, Any]] = None,
        method_contract: Optional[dict[str, Any]] = None,
        run_spec: Optional[dict[str, Any]] = None,
        implementation_blueprint: Optional[dict[str, Any]] = None,
    ) -> str:
        from .experiment_depth_supplement import build_depth_supplement

        return build_depth_supplement(
            selected, research_direction, selected_contract, method_contract,
            run_spec, implementation_blueprint,
        )















    def _accepted_snapshot_paths(
        self,
        run: WorkflowRun,
        node_id: str,
        gate: dict[str, Any],
        requirements: list[Path],
    ) -> list[Path]:
        from .engine_snapshot_paths import accepted_snapshot_paths

        return accepted_snapshot_paths(self, run, node_id, gate, requirements)






    def _validated_accepted_phase_ids(
        self,
        run: WorkflowRun,
        run_state: RunState,
    ) -> list[str]:
        from .accepted_phase_validation import validated_accepted_phase_ids

        return validated_accepted_phase_ids(self, run, run_state)





    def _revision_artifact_signature(
        self,
        project_path: str,
        node_id: str,
        options: Optional[dict[str, Any]] = None,
    ) -> str:
        from .engine_revision_signature import revision_artifact_signature

        return revision_artifact_signature(self, project_path, node_id, options)







    def _acceptance_gate(self, node: WorkflowNode, run: WorkflowRun, assurance: str, result: str, require_fresh: bool = True) -> dict:
        from .acceptance_coordinator import acceptance_gate

        return acceptance_gate(self, node, run, assurance, result, require_fresh)

    def _figure_acceptance_gate(self, project_path: str) -> dict:
        from .figure_acceptance_policy import figure_acceptance_gate

        return figure_acceptance_gate(self, project_path)



    def _paper_acceptance_gate(
        self, project_path: str, *, require_innovation: bool = False,
        require_page_budget: bool = False, require_staged: bool = False,
        paper_options: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        from .paper_acceptance_coordinator import paper_acceptance_gate

        return paper_acceptance_gate(
            self, project_path, require_innovation=require_innovation,
            require_page_budget=require_page_budget, require_staged=require_staged,
            paper_options=paper_options,
        )
    @classmethod
    def _review_layout_revision_findings(
        cls,
        project_path: str,
        state_data: dict[str, Any],
    ) -> list[dict[str, Any]]:
        from .review_layout_findings import review_layout_revision_findings

        return review_layout_revision_findings(project_path, state_data)

    @staticmethod
    def _review_visual_evidence_gate(
        project_path: str,
        state_data: dict[str, Any],
        structured_rounds: list[dict[str, Any]],
    ) -> dict[str, Any]:
        from .review_visual_evidence import review_visual_evidence_gate

        return review_visual_evidence_gate(project_path, state_data, structured_rounds)

    def _review_acceptance_gate(
        self,
        project_path: str,
        review_started_at: Optional[float] = None,
        delivery_goal: str = "submission_candidate",
    ) -> dict:
        from .review_acceptance_policy import review_acceptance_gate

        return review_acceptance_gate(self, project_path, review_started_at=review_started_at, delivery_goal=delivery_goal)







    async def _resume_persisted_run_claimed(
        self,
        run_id: str,
        project_path: str,
        node_ids: Optional[list[str]] = None,
        research_direction: str = "",
        effort: str = "",
        assurance: str = "",
        pipeline_options: Optional[dict] = None,
        on_event: Optional[Callable] = None,
        checkpoint_feedback: str = "",
        resume_source: str = "explicit",
    ) -> str:
        from .resume_execution import resume_persisted_run_claimed

        return await resume_persisted_run_claimed(
            self, run_id=run_id, project_path=project_path, node_ids=node_ids,
            research_direction=research_direction, effort=effort, assurance=assurance,
            pipeline_options=pipeline_options, on_event=on_event,
            checkpoint_feedback=checkpoint_feedback, resume_source=resume_source,
        )











    # ==================== 查询 ====================






# 全局实例
workflow_engine = WorkflowEngine()
