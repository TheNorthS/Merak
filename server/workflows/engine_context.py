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







__all__ = [name for name in globals() if not name.startswith('__')]
