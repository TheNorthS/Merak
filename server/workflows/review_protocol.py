"""Transport bounds, prompts, parsing, and failure state for review rounds."""

from __future__ import annotations

import asyncio
import contextlib
import json
import time
from typing import Any, Optional

from .review_models import ReviewRound, ReviewState
from .draft_delivery import draft_blockers


class ReviewProtocolMixin:
    @staticmethod
    async def _run_fix_with_progress(
        operation: Any, *, timeout_seconds: float,
        on_progress: Optional[Any], progress_label: str,
        last_activity: Optional[Any] = None,
        idle_timeout_seconds: Optional[float] = None,
    ) -> str:
        from . import review_audit

        heartbeat = float(review_audit.REVIEW_FIX_HEARTBEAT_SECONDS)
        idle_limit = float(
            idle_timeout_seconds
            if idle_timeout_seconds is not None
            else review_audit.REVIEW_AGENT_IDLE_TIMEOUT_SECONDS
        )
        task = asyncio.create_task(operation())
        started = time.monotonic()
        try:
            while True:
                now = time.monotonic()
                remaining = timeout_seconds - (now - started)
                idle_for = (
                    max(0.0, now - float(last_activity()))
                    if last_activity is not None else 0.0
                )
                idle_remaining = (
                    max(0.0, idle_limit - idle_for)
                    if last_activity is not None else remaining
                )
                if remaining <= 0 or idle_remaining <= 0:
                    kind = "idle" if idle_remaining <= 0 else "hard wall-time"
                    limit = idle_limit if idle_remaining <= 0 else timeout_seconds
                    raise asyncio.TimeoutError(
                        f"{progress_label} exceeded {kind} limit {limit:.0f}s"
                    )
                done, _ = await asyncio.wait(
                    {task}, timeout=min(heartbeat, remaining, idle_remaining)
                )
                if task in done:
                    return await task
                if on_progress:
                    await on_progress(
                        f"{progress_label}: operation still running "
                        f"({int(time.monotonic() - started)}s; idle {int(idle_for)}s)"
                    )
        finally:
            if not task.done():
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await task

    @staticmethod
    def _is_bounded_transport_error(error: Exception) -> bool:
        text = str(error).casefold()
        return isinstance(
            error, (asyncio.TimeoutError, TimeoutError, ConnectionError)
        ) or any(marker in text for marker in (
            "timeout", "timed out", "请求超时", "502", "503", "bad gateway",
            "connection reset", "peer closed connection", "incomplete chunked read",
        ))

    def _record_review_transport_failure(
        self, state: ReviewState, project_path: str, error: Exception,
        round_num: int, current_pdf_snapshot: dict[str, Any],
        review_image_paths: list[str], review_image_bundle_sha256: str,
    ) -> None:
        state.transport_failure = {
            "round": int(round_num), "error_type": type(error).__name__,
            "error": str(error)[:2000], "failed_at": time.time(),
            "review_input_snapshot": str(
                current_pdf_snapshot.get("snapshot_path") or ""
            ),
            "review_input_pdf_sha256": str(
                current_pdf_snapshot.get("pdf_sha256") or ""
            ),
            "review_image_paths": list(review_image_paths),
            "review_image_bundle_sha256": review_image_bundle_sha256,
        }
        state.current_round = round_num
        state.threshold_met = False
        state.bounded_complete = False
        state.is_complete = False
        state.publication_ready = False
        state.phase = "review_transport_failed"
        self._save_state(state, project_path)

    @staticmethod
    def _get_reviewer_prompt(
        difficulty: str, evidence_mode: str = "executed"
    ) -> str:
        base = _BASE_REVIEW_PROMPT
        if evidence_mode == "synthetic_preview":
            base += _SIMULATION_REVIEW_POLICY
        elif evidence_mode in {"design_only", "execution_pending", "planned"}:
            base += _PLANNED_REVIEW_POLICY
        if difficulty == "hard":
            base += "\n\n你特别严格。关注实验方法论缺陷、统计显著性不足、声明过强等问题。"
        elif difficulty == "nightmare":
            base += "\n\n你是最严格的审稿人。对每个声明都要求充分的证据支持。对实验设计的任何瑕疵零容忍。"
        return base

    @staticmethod
    def _parse_review(
        review_text: str, round_num: int, *, pdf_snapshot: str = ""
    ) -> ReviewRound:
        from .review_audit import _extract_json_object

        try:
            data = _extract_json_object(review_text, "score")
            if data:
                raw_visual = data.get("visual_review")
                visual = {
                    str(key): str(value) for key, value in raw_visual.items()
                    if str(key).strip() and str(value).strip()
                } if isinstance(raw_visual, dict) else {}
                return ReviewRound(
                    round_number=round_num,
                    score=float(data.get("score", 5)),
                    verdict=data.get("verdict", "needs_work"),
                    strengths=data.get("strengths", []),
                    weaknesses=data.get("weaknesses", []),
                    action_items=data.get("action_items", []),
                    raw_review=review_text, pdf_snapshot=pdf_snapshot,
                    visual_review=visual,
                    draft_blockers=draft_blockers(data.get("draft_blockers")),
                )
        except (json.JSONDecodeError, ValueError):
            pass
        raise ValueError(
            "Independent reviewer returned no schema-conforming review JSON"
        )


_BASE_REVIEW_PROMPT = """你是一位严格的学术审稿人（来自顶级会议 PC）。
你的任务是以批判性视角审稿，指出论文的弱点和问题。

评分标准（1-10）：
- 1-3: 严重问题，不适合发表
- 4-5: 有明显弱点需要大改
- 6-7: 基本可以，小修后可接受
- 8-9: 优秀论文
- 10: 完美（极罕见）

审稿维度：Novelty, Soundness, Significance, Clarity, Reproducibility

输出格式（JSON）：
{"score": N, "verdict": "ready|almost|needs_work|major_revision", "strengths": [...], "weaknesses": [...], "action_items": [...], "visual_review": {"pdf_path": "...", "figure_quality": "...", "caption_alignment": "...", "page_layout": "...", "table_formatting": "...", "visual_consistency": "..."}}

visual_review 是强制验收字段。必须基于本轮 freshly compiled PDF 和渲染页检查，
不能仅从 LaTeX 源码猜测；缺少任何一个子字段时，本轮不能判定 ready/almost。
所有模式均不得建议或添加可见水印、草稿印章、警告横幅/框、角标、页眉页脚状态、
边注警告或图题表题中的证据状态提示；这些内部状态只能留在机器侧车。"""

_SIMULATION_REVIEW_POLICY = """

当前稿件是一篇完整的固定基准研究，不是 planned / pre-experiment 协议稿。
- 按完整定量论文审查主对比、消融、训练或收敛动态、鲁棒性、误差切片、校准/风险覆盖、效率权衡及其不确定性分析。
- 不要仅因结果来自固定基准而把完整性评分压低；检查生成契约、固定种子、场景定义、统计口径和结论边界是否自洽且可复现。
- 不得把未运行物理训练或 train.py smoke test 本身当作拒稿理由。
- 只有生成器不可重建、场景/原始记录/统计不一致、证据溯源断裂或结论越界时，才把执行完整性列为 blocker。
- 若结论超出定义基准，或把基准结果冒充未经声明的外部测量，必须 major_revision。
- 科学正文和图表必须如实描述 simulation/synthetic 数据的生成机制、固定配置、统计定义和适用范围；Methods 中的可复现描述不能由末尾披露替代。Conclusion 后、参考文献前仍保留一次统一 Simulation Study Disclosure。
- 不得添加 NOT FOR SUBMISSION 警告、预览标签、水印或图题表题内部状态。"""

_PLANNED_REVIEW_POLICY = """

当前稿件处于 planned / pre-experiment 阶段。评分表示阶段就绪度，不是投稿接收概率。
- 没有真实指标本身不是本节点可修复缺陷；把它记录为投稿前证据缺口。
- 严格检查 Idea 冻结、方法形式化、实验可执行和可证伪、baseline/消融/统计/泄漏控制。
- 若稿件伪造结果或暗示已完成未执行的物理/临床/现场实验，必须 major_revision。
- 不得把内部状态或 claim ID 塞进论文正文。"""
