"""Bounded independent-review loop with targeted, reversible fixes."""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import structlog

from ..agent import ModelRole, model_router
from ..agent.engine import agent_engine
from ..services.simulation_policy import is_complete_evidence_mode
from ..utils.atomic_write import atomic_write_bytes
from .review_models import (
    NATIVE_VISUAL_REVIEW_TRANSPORTS,
    ReviewRound,
    ReviewState,
)
from .review_visuals import ReviewSnapshotRequest
from .draft_delivery import DRAFT, DRAFT_POLICY, run_delivery_goal

logger = structlog.get_logger()

_ALLOWED_MODES = {
    "executed", "existing_results", "secondary_analysis", "design_only",
    "synthetic_preview", "execution_pending", "planned",
}
_NON_EMPIRICAL = {"design_only", "execution_pending", "planned"}
_BOUNDED_FALLBACK = {*_NON_EMPIRICAL, "synthetic_preview"}


@dataclass
class ReviewContext:
    reviewer: Any
    paper_path: str
    project_path: str
    max_rounds: int
    difficulty: str
    on_progress: Optional[Any]
    run_id: str
    researcher_feedback: str
    evidence_mode: str
    transport_retry: Optional[Any]
    executor_name: str = ""
    executor_identity: str = ""
    reviewer_name: str = ""
    reviewer_identity: str = ""
    owner_policy: str = ""
    reviewer_prompt: str = ""
    delivery_goal: str = "submission_candidate"
    review_policy_sha256: str = ""


async def run_review_loop(context: ReviewContext) -> ReviewState:
    state, cached = _initialize_state(context)
    if cached:
        return state
    _load_owner_policy(context, state)
    _bind_routes(context, state)
    start_round = _start_round(state, context.max_rounds)
    for round_number in range(start_round, context.max_rounds + 1):
        stop = await _run_round(context, state, round_number)
        if stop:
            break
    _finalize_state(context, state)
    context.reviewer._save_state(state, context.project_path)
    return state


def _initialize_state(context: ReviewContext) -> tuple[ReviewState, bool]:
    from .review_audit import review_source_bundle
    context.delivery_goal = run_delivery_goal(context.project_path, context.run_id)

    context.evidence_mode = (
        context.evidence_mode if context.evidence_mode in _ALLOWED_MODES
        else "design_only"
    )
    context.executor_name, _, context.executor_identity = model_router.get_provider_route(
        ModelRole.EXECUTOR
    )
    context.reviewer_name, _, context.reviewer_identity = (
        model_router.get_isolated_provider_route(
            ModelRole.REVIEWER,
        )
    )
    requested_id = context.run_id or uuid.uuid4().hex[:12]
    source_hash, _ = review_source_bundle(context.project_path)
    persisted = context.reviewer._load_state(
        context.project_path, run_id=requested_id,
        max_rounds=context.max_rounds, evidence_mode=context.evidence_mode,
    )
    from .review_policy_fingerprint import review_policy_fingerprint
    context.review_policy_sha256 = review_policy_fingerprint(context)
    if persisted is not None and (persisted.delivery_goal != context.delivery_goal
            or persisted.review_policy_sha256 != context.review_policy_sha256):
        from .draft_delivery import archive_previous_review
        archive_previous_review(context.project_path)
        persisted = None
    cached = _cached_state_valid(
        context, persisted, source_hash
    )
    if cached:
        return persisted, True
    resumable = bool(
        persisted is not None and not persisted.is_complete
        and persisted.source_bundle_sha256 == source_hash
    )
    state = persisted if resumable else ReviewState(
        run_id=requested_id, max_rounds=context.max_rounds,
        evidence_mode=context.evidence_mode,
        delivery_goal=context.delivery_goal,
        review_policy_sha256=context.review_policy_sha256,
    )
    if not resumable:
        from .draft_delivery import archive_previous_review
        archive_previous_review(context.project_path)
    if not state.source_bundle_sha256:
        state.source_bundle_sha256 = source_hash
    return state, False


def _cached_state_valid(
    context: ReviewContext, state: ReviewState | None, source_hash: str
) -> bool:
    if state is None or not state.is_complete or not state.rounds:
        return False
    last = state.rounds[-1]
    return bool(
        state.source_bundle_sha256 == source_hash
        and bool(context.review_policy_sha256)
        and state.review_policy_sha256 == context.review_policy_sha256
        and state.executor_model == context.executor_identity
        and state.reviewer_model == context.reviewer_identity
        and last.has_complete_visual_review()
        and str(last.visual_review.get("_source_bundle_sha256") or "") == source_hash
        and context.reviewer._pdf_snapshot_for_source(
            state, context.project_path, round_number=state.current_round,
            source_sha256=source_hash,
        ) is not None
    )


def _load_owner_policy(context: ReviewContext, state: ReviewState) -> None:
    from ..services.skill_orchestrator import skill_orchestrator
    from ..services.skill_registry import skill_registry

    if not skill_registry.get_skill(state.owner_skill):
        from os import environ

        skill_registry.scan_directory(
            Path(environ.get("MERAK_SKILLS_PATH") or Path(__file__).parents[2] / "merak-skills")
        )
    context.owner_policy = skill_orchestrator.full_policy(state.owner_skill)
    if not context.owner_policy:
        raise RuntimeError(
            f"The review coordinator cannot load /{state.owner_skill} SKILL.md"
        )
    state.policy_loaded = True
    context.reviewer_prompt = (
        context.reviewer._get_reviewer_prompt(
            context.difficulty, context.evidence_mode
        )
        + "\n\n## Loaded MERAK Skill Invocation\n"
        + f"Skill: /{state.owner_skill}\n"
        + "The complete SKILL.md below is the operating policy for the managed "
        + "review loop. Apply its review criteria and evidence invariants; the "
        + "MERAK coordinator owns persistence and round control.\n\n"
        + context.owner_policy
        + "\n\n## Managed Phase Scope\n"
        + "This fresh reviewer performs Phase A review only. Read current artifacts "
        + "directly and return the requested JSON. Do not use prior round summaries "
        + "or invoke nested reviewers. The required visual_review object is mandatory."
    )


def _bind_routes(context: ReviewContext, state: ReviewState) -> None:
    changed = bool(
        state.rounds and (
            (state.executor_model and state.executor_model != context.executor_identity)
            or (state.reviewer_model and state.reviewer_model != context.reviewer_identity)
        )
    )
    if changed:
        state.rounds = []
        state.current_round = 0
        state.final_score = 0
        state.final_verdict = ""
        state.is_complete = state.threshold_met = state.bounded_complete = False
        state.publication_ready = False
        state.fallback_reason = ""
        state.phase = "pending"
        state.reviewer_session_ids = []
        state.executor_session_ids = []
        state.pdf_snapshots = []
    state.executor_provider = context.executor_name
    state.reviewer_provider = context.reviewer_name
    state.executor_model = context.executor_identity
    state.reviewer_model = context.reviewer_identity
    logger.info(
        "Review loop starting", executor=state.executor_model,
        reviewer=state.reviewer_model, max_rounds=context.max_rounds,
    )


def _start_round(state: ReviewState, maximum: int) -> int:
    if state.current_round <= 0:
        start = 1
    elif state.phase == "round_complete":
        start = state.current_round + 1
    else:
        start = state.current_round
    return min(maximum + 1, max(1, start))


async def _run_round(
    context: ReviewContext, state: ReviewState, round_number: int
) -> bool:
    from .review_audit import review_source_bundle

    state.current_round = round_number
    source_hash, source_paths = review_source_bundle(context.project_path)
    state.source_bundle_sha256 = source_hash
    snapshot = await _review_input_snapshot(
        context, state, round_number, source_hash
    )
    # The print producer may have installed same-science typography overlays.
    # Freeze native reviewer inputs only after that real output exists.
    source_hash, source_paths = review_source_bundle(context.project_path)
    if snapshot.get("source_bundle_sha256") != source_hash:
        raise RuntimeError("Review input snapshot is stale for the current printed manuscript sources")
    state.source_bundle_sha256 = source_hash
    review_round = await _invoke_independent_review(
        context, state, round_number, snapshot, source_hash, source_paths
    )
    if context.on_progress:
        await context.on_progress(
            f"Round {round_number}: Score {review_round.score}/10 — {review_round.verdict}"
        )
    if await _accept_threshold(context, state, review_round, round_number):
        return True
    if round_number >= context.max_rounds:
        state.phase = "round_complete"
        await _compile_output_snapshot(
            context, state, round_number, "bounded-final-review"
        )
        return False
    return await _repair_round(context, state, review_round, round_number)


async def _review_input_snapshot(
    context: ReviewContext, state: ReviewState,
    round_number: int, source_hash: str,
) -> dict[str, Any]:
    snapshot_round = max(0, round_number - 1)
    snapshot = context.reviewer._pdf_snapshot_for_source(
        state, context.project_path, round_number=snapshot_round,
        source_sha256=source_hash,
    )
    if snapshot is not None:
        return snapshot
    return await context.reviewer._compile_review_snapshot(state, ReviewSnapshotRequest(
        project_path=context.project_path, paper_path=context.paper_path,
        round_number=snapshot_round, original=snapshot_round == 0,
        reason=f"round-{round_number}-review-input", on_progress=context.on_progress,
    ))


async def _invoke_independent_review(
    context: ReviewContext, state: ReviewState, round_number: int,
    snapshot: dict[str, Any], source_hash: str, source_paths: list[Path],
) -> ReviewRound:
    from ..services.api_visual_reviewer import api_visual_reviewer
    from .review_audit import REVIEW_MODEL_CALL_TIMEOUT_SECONDS, _save_trace

    if context.on_progress:
        await context.on_progress(
            f"Round {round_number}/{context.max_rounds}: Reviewing..."
        )
    images = context.reviewer._native_review_image_paths(
        context.project_path, snapshot
    )
    image_hash = context.reviewer._visual_bundle_sha256(
        Path(context.project_path).expanduser().resolve(), images
    )
    prompt = _review_input(context, round_number, snapshot, images)
    activity = {"at": time.monotonic()}
    transport: dict[str, str] = {}

    async def invoke_raw() -> str:
        result = await api_visual_reviewer.review_manuscript(
            project_path=context.project_path,
            prompt=context.reviewer_prompt + "\n\n" + prompt,
            round_number=round_number,
            timeout_seconds=REVIEW_MODEL_CALL_TIMEOUT_SECONDS,
            on_activity=lambda: activity.update(at=time.monotonic()),
            image_paths=images, evidence_paths=source_paths,
            evidence_bundle_sha256=source_hash,
            **({"delivery_goal": DRAFT} if context.delivery_goal == DRAFT else {}),
        )
        state.reviewer_provider = result.provider_name
        state.reviewer_model = result.model_identity
        state.reviewer_session_ids.append(result.invocation_id)
        transport.update(trace_path=result.trace_path,
                         invocation_id=result.invocation_id,
                         model_identity=result.model_identity)
        activity["at"] = time.monotonic()
        return result.text

    async def invoke() -> str:
        return await context.reviewer._run_fix_with_progress(
            invoke_raw, timeout_seconds=REVIEW_MODEL_CALL_TIMEOUT_SECONDS,
            on_progress=context.on_progress,
            progress_label=f"Round {round_number} review",
            last_activity=lambda: activity["at"],
        )

    state.phase = "reviewing"
    state.transport_failure = {}
    state.fallback_reason = ""
    context.reviewer._save_state(state, context.project_path)
    try:
        text = await context.transport_retry(
            f"round-{round_number}-review", invoke
        ) if context.transport_retry is not None else await invoke()
    except Exception as exc:
        if context.reviewer._is_bounded_transport_error(exc):
            context.reviewer._record_review_transport_failure(
                state, context.project_path, exc, round_number,
                snapshot, images, image_hash,
            )
        raise
    _save_trace(context.project_path, state.owner_skill,
                f"round={round_number}\n{prompt}", text)
    return _parse_and_attest_review(
        context, state, round_number, snapshot, images, image_hash, transport, text
    )


def _review_input(
    context: ReviewContext, round_number: int,
    snapshot: dict[str, Any], images: list[str],
) -> str:
    from datetime import datetime, timezone
    text = (
        f"Current UTC date: {datetime.now(timezone.utc).date().isoformat()}. "
        "Judge publication dates against this runtime date, not your training cutoff. "
        "Retrieval receipts establish observed metadata, not full-text methodological claims. "
        f"这是第 {round_number}/{context.max_rounds} 轮独立冷启动审稿。"
        "你看不到执行器解释、上一轮修订摘要或上一位审稿人的判断。"
        f"请从磁盘重新读取当前论文（文件路径：{context.paper_path}）。当前证据模式为 "
        f"{context.evidence_mode}。给出 1-10 分阶段就绪度评分、verdict"
        "（ready/almost/needs_work/major_revision）、strengths、weaknesses、"
        "action_items。以 JSON 格式输出。每条 action_items 必须以 "
        "[owner=lit|idea|exp-design|exp-run|results|figure|paper] 开头，"
        "并在可定位时附 [target=项目相对路径]。target 必须是该 owner 可写的规范产物；"
        "若同时需要上游证据和论文更新，拆成两条 action_item。"
    )
    text += context.reviewer._pdf_review_context(
        context.project_path, snapshot, review_images=images
    )
    if context.researcher_feedback.strip():
        text += "\n\n研究者定向反馈（本轮必须优先处理）：\n" + context.researcher_feedback.strip()
    if context.delivery_goal == DRAFT:
        text += "\n\n" + DRAFT_POLICY
    from ..services.simulation_identity_evidence import simulation_identity_evidence
    text += simulation_identity_evidence(Path(context.project_path))
    return text


def _parse_and_attest_review(
    context: ReviewContext, state: ReviewState, round_number: int,
    snapshot: dict[str, Any], images: list[str], image_hash: str,
    transport: dict[str, str], text: str,
) -> ReviewRound:
    try:
        review = context.reviewer._parse_review(
            text, round_number,
            pdf_snapshot=str(snapshot.get("snapshot_path") or ""),
        )
    except ValueError as exc:
        state.threshold_met = state.bounded_complete = state.is_complete = False
        state.publication_ready = False
        state.phase = "review_output_invalid"
        state.fallback_reason = f"reviewer_output_invalid: {type(exc).__name__}: {exc}"[:2000]
        context.reviewer._save_state(state, context.project_path)
        raise
    declared_matches = _declared_pdf_matches(
        context.project_path, review, snapshot
    )
    review_transport = "independent-model-api-native-vision-v1"
    review.visual_review.update({
        "_coordinator_verified": "true" if (
            declared_matches and images and image_hash
            and review_transport in NATIVE_VISUAL_REVIEW_TRANSPORTS
        ) else "false",
        "_source_bundle_sha256": str(snapshot.get("source_bundle_sha256") or ""),
        "_pdf_sha256": str(snapshot.get("pdf_sha256") or ""),
        "_visual_bundle_sha256": str(snapshot.get("visual_bundle_sha256") or ""),
        "_visual_content_sha256": str(snapshot.get("visual_content_sha256") or ""),
        "_review_image_paths": json.dumps(images, ensure_ascii=False, separators=(",", ":")),
        "_review_image_bundle_sha256": image_hash,
        "_review_response_sha256": hashlib.sha256(text.strip().encode()).hexdigest(),
        "_review_transport": review_transport,
        "_review_trace_path": str(transport.get("trace_path") or ""),
        "_review_invocation_id": str(transport.get("invocation_id") or ""),
        "_review_model_identity": str(transport.get("model_identity") or ""),
    })
    if state.rounds and state.rounds[-1].round_number == round_number:
        state.rounds[-1] = review
    else:
        state.rounds.append(review)
    state.phase = "reviewed"
    context.reviewer._save_state(state, context.project_path)
    return review


def _declared_pdf_matches(
    project_path: str, review: ReviewRound, snapshot: dict[str, Any]
) -> bool:
    declared = str(review.visual_review.get("pdf_path") or "").strip()
    allowed = {
        str(snapshot.get("current_pdf_path") or "").replace("\\", "/"),
        str(snapshot.get("snapshot_path") or "").replace("\\", "/"),
    }
    if declared.replace("\\", "/") in allowed:
        return True
    if not declared:
        return False
    root = Path(project_path).expanduser().resolve()
    path = Path(declared).expanduser()
    path = (path if path.is_absolute() else root / path).resolve()
    return any(path == (root / candidate).resolve() for candidate in allowed if candidate)


async def _accept_threshold(
    context: ReviewContext, state: ReviewState,
    review: ReviewRound, round_number: int,
) -> bool:
    if context.delivery_goal == DRAFT:
        if review.draft_blockers is None:
            raise ValueError("Independent review omitted draft_blockers")
        if review.draft_blockers:
            return False
        state.final_score, state.final_verdict = review.score, review.verdict
        state.threshold_met = state.should_stop()
        state.publication_ready = False
        return await _complete_without_fix(context, state, round_number, "",
            "draft-review-complete", "draft integrity review completed; scientific score and findings retained")
    if not state.should_stop():
        return False
    state.threshold_met = state.bounded_complete = state.is_complete = True
    state.final_score = review.score
    state.final_verdict = review.verdict
    state.publication_ready = is_complete_evidence_mode(context.evidence_mode)
    state.phase = "completed"
    await _compile_output_snapshot(context, state, round_number, "accepted-review")
    logger.info("Review loop stopped — threshold met", score=review.score)
    return True


async def _repair_round(
    context: ReviewContext, state: ReviewState,
    review: ReviewRound, round_number: int,
) -> bool:
    from .review_audit import build_review_fix_scope

    from dataclasses import replace
    scoped = replace(review, action_items=list(review.draft_blockers or []), weaknesses=[]) if context.delivery_goal == DRAFT else review
    actions, targets = build_review_fix_scope(context.project_path, context.paper_path, scoped)
    root = Path(context.project_path).expanduser().resolve()
    labels = [path.relative_to(root).as_posix() for path in targets]
    from ..services.paper_canonical_author_target import runtime_presentation_target
    if any(runtime_presentation_target(root, label) for label in labels):
        return await _complete_without_fix(
            context, state, round_number, "runtime_presentation_revision_required", "print-owner-handoff",
            "findings require the runtime print producer; derived-file model editing stopped",
        )
    if _requires_upstream_handoff(actions, labels):
        return await _complete_without_fix(
            context, state, round_number, "upstream_research_revision_required",
            "upstream-handoff",
            "findings require an upstream research owner; manuscript editing stopped",
        )
    if not actions or not targets:
        return await _complete_without_fix(
            context, state, round_number, "revision_scope_unresolved",
            "no-local-fix-scope",
            "reviewer supplied no actionable existing-file repair scope",
        )
    if context.on_progress:
        await context.on_progress(
            f"Round {round_number}: fixing {len(actions)} prioritized item(s) "
            f"in {len(labels)} targeted file(s): " + ", ".join(labels)
        )
    return await _perform_fix(
        context, state, review, round_number, actions, targets, labels
    )


def _requires_upstream_handoff(actions: list[str], labels: list[str]) -> bool:
    text = " ".join(actions).casefold()
    declared = any(f"[owner={owner}]" in text for owner in (
        "lit", "idea", "exp-design", "exp-run", "results", "figure"
    ))
    upstream_target = any(
        label.split("/", 1)[0].casefold()
        in {"experiments", "figures", "literature", "ideas"}
        for label in labels
    )
    markers = (
        "missing baseline", "missing ablation", "data leakage", "split protocol",
        "training failed", "run failed", "experiment was not run", "per-seed",
        "confidence interval", "metric provenance", "prediction file",
        "implementation mismatch", "缺少基线", "缺少消融", "数据泄漏", "划分协议",
        "训练失败", "实验未运行", "随机种子", "置信区间", "结果溯源",
    )
    return declared or upstream_target or any(marker in text for marker in markers)


async def _complete_without_fix(
    context: ReviewContext, state: ReviewState, round_number: int,
    reason: str, snapshot_reason: str, progress: str,
) -> bool:
    state.bounded_complete = state.is_complete = True
    state.fallback_reason = reason
    state.phase = "completed"
    await _compile_output_snapshot(context, state, round_number, snapshot_reason)
    context.reviewer._save_state(state, context.project_path)
    if context.on_progress:
        await context.on_progress(f"Round {round_number}: {progress}")
    return True


async def _perform_fix(
    context: ReviewContext, state: ReviewState, review: ReviewRound,
    round_number: int, actions: list[str], targets: list[Path], labels: list[str],
) -> bool:
    from .review_audit import (
        REVIEW_FIX_CALL_TIMEOUT_SECONDS,
        REVIEW_PARTIAL_STREAM_TIMEOUT_SECONDS,
        _save_trace,
        review_source_bundle,
    )

    before_hash, _ = review_source_bundle(context.project_path)
    snapshots = {path: path.read_bytes() for path in targets if path.is_file()}
    session, instruction = _fix_session_and_instruction(
        context, state, actions, targets, labels
    )
    activity = {"at": time.monotonic()}

    async def fix_event(_event: Any) -> None:
        activity["at"] = time.monotonic()

    async def invoke_fix() -> str:
        return await agent_engine.run(
            session_id=session.id, user_message=instruction,
            on_event=fix_event, tools=["Read", "Edit"], max_tokens=2400,
            partial_stream_timeout_seconds=REVIEW_PARTIAL_STREAM_TIMEOUT_SECONDS,
        )

    state.phase = "fixing"
    context.reviewer._save_state(state, context.project_path)
    fix_text, bounded_error = "", ""
    try:
        fix_text = await context.reviewer._run_fix_with_progress(
            invoke_fix, timeout_seconds=REVIEW_FIX_CALL_TIMEOUT_SECONDS,
            on_progress=context.on_progress,
            progress_label=f"Round {round_number} targeted fix",
            last_activity=lambda: activity["at"],
        )
    except (asyncio.TimeoutError, TimeoutError, RuntimeError) as exc:
        state.bounded_complete = state.is_complete = False
        state.phase = "fix_interrupted"
        state.fallback_reason = str(exc) or type(exc).__name__
        context.reviewer._save_state(state, context.project_path)
        raise
    if fix_text:
        _save_trace(
            context.project_path, state.owner_skill,
            f"round={round_number}\ntargets={labels}\n{instruction}", fix_text,
        )
    after_hash, _ = review_source_bundle(context.project_path)
    if after_hash != before_hash and await _reconcile_fix(
        context, state, review, round_number, snapshots
    ):
        return True
    unchanged = after_hash == before_hash
    state.bounded_complete = state.is_complete = unchanged
    state.fallback_reason = (
        "revision_transport_timeout_without_source_change" if unchanged and bounded_error
        else "revision_produced_no_source_change" if unchanged else ""
    )
    state.phase = "completed" if unchanged else "round_complete"
    await _compile_output_snapshot(
        context, state, round_number,
        "unchanged-review" if unchanged else "targeted-fix",
    )
    context.reviewer._save_state(state, context.project_path)
    if unchanged and context.on_progress:
        await context.on_progress(
            f"Round {round_number}: no targeted source change; bounded review is complete"
        )
    return unchanged


def _fix_session_and_instruction(
    context: ReviewContext, state: ReviewState,
    actions: list[str], targets: list[Path], labels: list[str],
) -> tuple[Any, str]:
    system = (
        "你是论文定向修改专家。只处理列出的高优先级意见，只读取和编辑明确列出的既有文件。"
        "禁止扫描项目、创建新文件、重写整篇论文或修改上游研究契约。"
        f"\n\n## Loaded MERAK Skill Invocation\nSkill: /{state.owner_skill}\n"
        + context.owner_policy
        + "\n\n## Managed Phase Scope\nThis is one bounded fix call. Preserve evidence "
        "boundaries, LaTeX include structure, citations, and contrary evidence."
    )
    session = agent_engine.create_session(system_prompt=system, role=ModelRole.EXECUTOR)
    session.project_path = context.project_path
    session.context_key = f"skill-chain:{state.owner_skill}>fix-targeted"
    session.workflow_node_id = "review"
    session.tool_policy = "workflow_artifacts"
    session.provider_override = context.executor_name or None
    session.max_iterations = min(int(getattr(session, "max_iterations", 8) or 8), 8)
    session.tool_call_limits = {
        "Read": max(2, len(targets) * 2), "Edit": max(2, len(targets) * 2),
    }
    state.executor_session_ids.append(session.id)
    instruction = (
        "执行一次定向修订。可修改文件仅限：\n"
        + "\n".join(f"- {path}" for path in labels)
        + "\n\n按优先级处理以下意见（不要扩展任务范围）：\n"
        + "\n".join(f"- {item}" for item in actions)
        + "\n\n先 Read 目标文件，再用 Edit 做最小必要修改。不得调用 Write，不得创建替代文件；"
        "完成后用不超过 100 字总结。任何模式都不得添加可见水印、草稿印章、"
        "警告横幅/框、角标、页眉页脚状态、边注警告或图题表题中的状态提示。"
    )
    if context.evidence_mode == "synthetic_preview":
        instruction += (
            "\n\n当前是完整的固定基准研究。可以修订对已注册主对比、消融、训练动态、"
            "鲁棒性、误差、校准和效率结果的分析，但不得改写机器结果、杜撰新数值或把结论"
            "扩展到基准之外。必须在科学正文如实描述仿真/simulation/synthetic 数据生成方法、固定配置和统计解释；"
            "内部路径、运行身份、preview 状态只保留在机器侧车，不得增加水印或状态提示。main.tex 末尾的统一仿真研究说明"
            "由组装器管理，不得删除、移动、重复或改写。"
        )
    elif context.evidence_mode in _NON_EMPIRICAL:
        instruction += (
            "\n\n当前未运行实验。只能完善方法、实验协议、引用、证据边界和写作；"
            "不得生成、暗示或填入实测结果。"
        )
    if context.researcher_feedback.strip():
        instruction += "\n\nResearcher feedback:\n" + context.researcher_feedback.strip()
    return session, instruction


async def _reconcile_fix(
    context: ReviewContext, state: ReviewState, review: ReviewRound,
    round_number: int, snapshots: dict[Path, bytes],
) -> bool:
    staged_state = Path(context.project_path) / "paper" / "DRAFT_STATE.json"
    if not staged_state.is_file():
        return False
    from ..services.paper_drafting import paper_drafting_service

    reconciliation = paper_drafting_service.reconcile_reviewed_artifacts(
        context.project_path, reviewer=f"managed-review-round-{round_number}"
    )
    if reconciliation.get("passed"):
        return False
    for path, payload in snapshots.items():
        atomic_write_bytes(path, payload)
    restored = paper_drafting_service.reconcile_reviewed_artifacts(
        context.project_path,
        reviewer=f"managed-review-round-{round_number}-rollback",
    )
    issues = [str(item) for item in reconciliation.get("issues", []) if str(item).strip()]
    review.weaknesses.append(
        "The proposed targeted revision was rejected because it regressed the validated manuscript contract."
    )
    review.action_items.extend(issues[:4])
    state.bounded_complete = state.is_complete = True
    state.fallback_reason = (
        "targeted_fix_rejected_by_paper_contract" if restored.get("passed")
        else "targeted_fix_rollback_requires_paper_repair"
    )
    state.phase = "completed"
    await _compile_output_snapshot(context, state, round_number, "contract-rollback")
    if context.on_progress:
        await context.on_progress(
            f"Round {round_number}: targeted edit regressed the paper contract and "
            "was rolled back; review findings remain advisory"
        )
    return True


async def _compile_output_snapshot(
    context: ReviewContext, state: ReviewState,
    round_number: int, reason: str,
) -> None:
    await context.reviewer._compile_review_snapshot(state, ReviewSnapshotRequest(
        project_path=context.project_path, paper_path=context.paper_path,
        round_number=round_number, original=False,
        reason=f"round-{round_number}-{reason}", on_progress=context.on_progress,
    ))


def _finalize_state(context: ReviewContext, state: ReviewState) -> None:
    if not state.threshold_met:
        state.final_score = state.rounds[-1].score if state.rounds else 0
        state.final_verdict = state.rounds[-1].verdict if state.rounds else "needs_work"
    if state.rounds and state.current_round >= state.max_rounds:
        state.bounded_complete = True
    state.is_complete = state.bounded_complete
    state.phase = "completed" if state.is_complete else state.phase
    state.publication_ready = bool(
        context.delivery_goal != DRAFT and is_complete_evidence_mode(context.evidence_mode)
        and state.final_score >= 6
        and state.final_verdict in {"ready", "almost"}
        and state.rounds and state.rounds[-1].has_complete_visual_review()
    )
