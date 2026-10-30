"""Independent model audit layers and proof-checker parsing."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from .review_models import AuditResult, Verdict


def proof_source_bundle(project_path: str):
    from .review_audit import proof_source_bundle as build

    return build(project_path)


def _extract_json_object(text: str, anchor: str):
    from .review_audit import _extract_json_object as extract

    return extract(text, anchor)


def _proof_prompts(
    chain: Any, source_paths: list[Path], theorem_count: int, evidence_mode: str
) -> tuple[str, str]:
    system = chain._system_prompt("proof-checker", _PROOF_SYSTEM_PROMPT)
    system += _PROOF_NATIVE_WRAPPER
    inventory = "\n".join(f"- {path}" for path in source_paths)
    audit_input = f"""Audit the current manuscript proof bundle for submission.
Evidence mode: {evidence_mode} (proof correctness is independent of empirical execution).
Runtime detector found {theorem_count} formal theorem/proof environments.

Declared theorem-bearing inputs (read every exact path):
{inventory}

Review only the frozen evidence packet. Return only the JSON verdict object."""
    return system, audit_input


def _complete_proof_result(
    result: AuditResult, theorem_count: int,
    source_paths: list[Path], root: Path,
) -> None:
    details = result.details if isinstance(result.details, dict) else {}
    details["formal_environments_detected"] = theorem_count
    details.setdefault("theorems_audited", theorem_count)
    details.setdefault("issues", [])
    result.details = details
    if not result.evidence:
        result.evidence = [
            path.relative_to(root).as_posix() if path.is_relative_to(root)
            else path.as_posix() for path in source_paths
        ]


_PROOF_SYSTEM_PROMPT = """You are the independent verdict-bearing proof reviewer for the native
MERAK submission audit. Apply the complete /proof-checker taxonomy, mandatory
checks, counterexample pass, and objective acceptance gate to the CURRENT
manuscript. This native pass is read-only: do not edit the manuscript and do
not claim that a gap was fixed. Inspect every declared theorem-bearing file.

Return exactly one JSON object with this shape:
{
  "audit_skill": "proof-checker",
  "verdict": "PASS|WARN|FAIL|BLOCKED|ERROR",
  "reason_code": "all_proofs_complete|minor_gaps|critical_gap|source_unreadable|reviewer_error",
  "summary": "one-line verdict",
  "details": {"theorems_audited": 1, "issues": []},
  "evidence": ["paper/main.tex"]
}

PASS is permitted only when the proof-checker acceptance gate is fully met.
Any open FATAL or CRITICAL issue requires FAIL. Do not return NOT_APPLICABLE,
because the runtime detector has already found formal proof content."""

_PROOF_NATIVE_WRAPPER = """

## Native submission wrapper (binding for this invocation)

The complete policy above is loaded as the mathematical review contract. This
runtime invocation is the independent, read-only submission verdict pass: it
executes proof inventory, obligation, counterexample, and acceptance-gate
checks, but cannot edit TeX or claim optional fix rounds. Emit only JSON."""


class AuditLayersMixin:
    async def _audit_experiment(self, paper_path: str, experiment_dir: str, project_path: str, evidence_mode: str, on_event: Optional[callable] = None) -> AuditResult:
        """Layer 1: 实验代码诚实性审计"""
        system_prompt = self._system_prompt("experiment-audit", """你是实验代码审计专家。检查以下潜在问题：
1. 伪造 ground truth（硬编码正确答案）
2. 自归一化评分（除以自身最大值）
3. 幻影结果（不存在的实验数据）
4. 数据泄露（测试集信息泄入训练）
5. 不公平对比（baseline 用弱配置）

以 JSON 输出：{"verdict": "PASS|WARN|FAIL|NOT_APPLICABLE", "summary": "...", "evidence": [...]}""")
        # The evidence-mode wrapper is invocation-specific and therefore must
        # follow the repository skill text.  When it preceded SKILL.md, broad
        # empirical anti-fabrication wording later in the prompt overrode the
        # selected simulation contract and rejected every valid simulation.
        system_prompt += "\n\n## Binding evidence-mode adjudication\n" + self._evidence_mode_policy(evidence_mode)

        audit_input = (
            f"请审计实验代码目录 {experiment_dir} 的诚实性。证据模式：{evidence_mode}。"
            + self._read_protocol(project_path, paper_path, experiment_dir)
        )
        result_text, session_id, model_identity, trace_path = await self._invoke_audit_reviewer(
            project_path=project_path,
            skill_name="experiment-audit",
            system_prompt=system_prompt,
            audit_input=audit_input,
            on_event=on_event,
        )

        return self._parse_audit_result(
            result_text,
            skill_name="experiment-audit",
            session_id=session_id,
            policy_loaded=self._policy_loaded("experiment-audit"),
            model_name=model_identity,
            trace_path=trace_path,
        )

    async def _audit_result_to_claim(self, paper_path: str, experiment_dir: str, project_path: str, evidence_mode: str, on_event: Optional[callable] = None) -> AuditResult:
        """Layer 2: 声明是否科学地跟随实验结果"""
        system_prompt = self._system_prompt("result-to-claim", """你是科学方法论审计员。检查：
1. 论文中的每个声明（claim）是否有实验数据支持
2. 声明的强度是否和数据匹配（不能过度声明）
3. 是否存在 cherry-picking（只展示有利结果）
4. 统计显著性是否充分

以 JSON 输出：{"verdict": "PASS|WARN|FAIL|NOT_APPLICABLE", "summary": "...", "evidence": [...]}""")
        system_prompt += "\n\n## Binding evidence-mode adjudication\n" + self._evidence_mode_policy(evidence_mode)

        audit_input = (
            f"请比对论文 {paper_path} 中的声明和实验目录 {experiment_dir} 中的实际结果。证据模式：{evidence_mode}。"
            + self._read_protocol(project_path, paper_path, experiment_dir)
        )
        result_text, session_id, model_identity, trace_path = await self._invoke_audit_reviewer(
            project_path=project_path,
            skill_name="result-to-claim",
            system_prompt=system_prompt,
            audit_input=audit_input,
            on_event=on_event,
        )

        return self._parse_audit_result(
            result_text,
            skill_name="result-to-claim",
            session_id=session_id,
            policy_loaded=self._policy_loaded("result-to-claim"),
            model_name=model_identity,
            trace_path=trace_path,
        )

    async def _audit_paper_claims(self, paper_path: str, experiment_dir: str, project_path: str, evidence_mode: str, on_event: Optional[callable] = None) -> AuditResult:
        """Layer 3: 论文中报告的数字是否和实验结果一致"""
        system_prompt = self._system_prompt("paper-claim-audit", """你是数字准确性审计员。检查：
1. 论文中的每个数字（准确率、loss、F1等）是否能在实验日志中找到
2. 表格中的数字是否和文本描述一致
3. 是否有四舍五入误导

以 JSON 输出：{"verdict": "PASS|WARN|FAIL|NOT_APPLICABLE", "summary": "...", "evidence": [...]}""")
        system_prompt += "\n\n## Binding evidence-mode adjudication\n" + self._evidence_mode_policy(evidence_mode)

        audit_input = (
            f"请核对论文 {paper_path} 中所有报告的数字是否和实验结果一致。证据模式：{evidence_mode}。"
            + self._read_protocol(project_path, paper_path, experiment_dir)
        )
        result_text, session_id, model_identity, trace_path = await self._invoke_audit_reviewer(
            project_path=project_path,
            skill_name="paper-claim-audit",
            system_prompt=system_prompt,
            audit_input=audit_input,
            on_event=on_event,
        )

        return self._parse_audit_result(
            result_text,
            skill_name="paper-claim-audit",
            session_id=session_id,
            policy_loaded=self._policy_loaded("paper-claim-audit"),
            model_name=model_identity,
            trace_path=trace_path,
        )

    async def _audit_citations(self, paper_path: str, experiment_dir: str, project_path: str, evidence_mode: str, on_event: Optional[callable] = None) -> AuditResult:
        """Layer 4: 引用审计"""
        system_prompt = self._system_prompt("citation-audit", r"""你是引用审计员。检查：
1. 每个 \cite{key} 是否在 .bib 文件中存在
2. 引用的论文是否真实存在（不是幻觉）
3. 引用上下文是否恰当（不能误引）

以 JSON 输出：{"verdict": "PASS|WARN|FAIL|NOT_APPLICABLE", "summary": "...", "evidence": [...]}""")
        system_prompt += "\n\n## Binding evidence-mode adjudication\n" + self._evidence_mode_policy(evidence_mode)

        audit_input = (
            f"请审计论文 {paper_path} 中所有引用的有效性。同时检查 .bib 文件。证据模式：{evidence_mode}。"
            + self._read_protocol(project_path, paper_path, experiment_dir)
        )
        result_text, session_id, model_identity, trace_path = await self._invoke_audit_reviewer(
            project_path=project_path,
            skill_name="citation-audit",
            system_prompt=system_prompt,
            audit_input=audit_input,
            on_event=on_event,
        )

        return self._parse_audit_result(
            result_text,
            skill_name="citation-audit",
            session_id=session_id,
            policy_loaded=self._policy_loaded("citation-audit"),
            model_name=model_identity,
            trace_path=trace_path,
        )

    async def _audit_kill_argument(self, paper_path: str, experiment_dir: str, project_path: str, evidence_mode: str, on_event: Optional[callable] = None) -> AuditResult:
        """Layer 5: 最强拒稿论点"""
        system_prompt = self._system_prompt("kill-argument", """你是 Area Chair，要写出最强的拒稿理由。

任务：写一个 200 字以内的拒稿备忘录（rejection memo），找出论文最致命的弱点。
这不是善意的建议，而是你能构造的最有力的拒绝论点。

然后，作为独立裁判，逐点评估这个拒稿论点是否成立。

输出 JSON：{"verdict": "PASS|WARN|FAIL|NOT_APPLICABLE", "summary": "最强拒稿论点...", "kill_memo": "200字拒稿备忘录", "adjudication": "对 kill_memo 的逐点裁定"}""")
        system_prompt += "\n\n## Binding evidence-mode adjudication\n" + self._evidence_mode_policy(evidence_mode)

        audit_input = (
            f"请对论文 {paper_path} 写出最强拒稿论点。证据模式：{evidence_mode}。"
            + self._read_protocol(project_path, paper_path, experiment_dir)
        )
        result_text, session_id, model_identity, trace_path = await self._invoke_audit_reviewer(
            project_path=project_path,
            skill_name="kill-argument",
            system_prompt=system_prompt,
            audit_input=audit_input,
            on_event=on_event,
        )

        return self._parse_audit_result(
            result_text,
            skill_name="kill-argument",
            session_id=session_id,
            policy_loaded=self._policy_loaded("kill-argument"),
            model_name=model_identity,
            trace_path=trace_path,
        )

    async def _audit_proofs(
        self, paper_path: str, experiment_dir: str, project_path: str,
        evidence_mode: str, on_event: Optional[callable] = None,
    ) -> AuditResult:
        del paper_path, experiment_dir
        _, input_hashes, source_paths, theorem_count, errors = proof_source_bundle(
            project_path
        )
        if errors or theorem_count <= 0:
            detector = self._proof_detector_result(project_path)
            if detector is None:
                raise RuntimeError("proof detector returned no reviewable inputs")
            return detector
        if not self._policy_loaded("proof-checker"):
            raise RuntimeError("Missing full skill policy: /proof-checker")
        system_prompt, audit_input = _proof_prompts(
            self, source_paths, theorem_count, evidence_mode
        )
        text, session_id, model_identity, api_trace = await self._invoke_audit_reviewer(
            project_path=project_path, skill_name="proof-checker",
            system_prompt=system_prompt, audit_input=audit_input,
            on_event=on_event,
        )
        root = Path(project_path).expanduser().resolve()
        trace = Path(api_trace).resolve()
        try:
            durable_trace = trace.relative_to(root).as_posix()
        except ValueError:
            durable_trace = trace.as_posix()
        result = self._parse_proof_audit_result(
            text, session_id=session_id,
            policy_loaded=self._policy_loaded("proof-checker"),
            model_name=model_identity, audited_input_hashes=input_hashes,
            trace_path=durable_trace,
        )
        _complete_proof_result(result, theorem_count, source_paths, root)
        return result
    def _parse_proof_audit_result(
        self,
        text: str,
        *,
        session_id: str,
        policy_loaded: bool,
        model_name: str,
        audited_input_hashes: dict[str, str],
        trace_path: str,
    ) -> AuditResult:
        """Parse proof-checker output without trusting reviewer provenance fields."""
        data = _extract_json_object(text, "verdict")
        if isinstance(data, dict):
            try:
                verdict = Verdict(str(data.get("verdict") or "ERROR").upper())
            except ValueError:
                verdict = Verdict.ERROR
            summary = str(data.get("summary") or "").strip()
            reason_code = str(data.get("reason_code") or "").strip()
            details = data.get("details")
            if not isinstance(details, dict):
                details = {
                    "theorems_audited": data.get("theorems_audited") or 0,
                    "issues": data.get("issues") if isinstance(data.get("issues"), list) else [],
                }
            evidence = data.get("evidence")
            evidence = evidence if isinstance(evidence, list) else []
            if summary and reason_code and verdict != Verdict.NOT_APPLICABLE:
                return AuditResult(
                    layer=6,
                    layer_name="Proof Checker",
                    verdict=verdict,
                    summary=summary,
                    details=details,
                    evidence=evidence,
                    method="model",
                    skill_name="proof-checker",
                    session_id=session_id,
                    policy_loaded=policy_loaded,
                    model_name=model_name,
                    reason_code=reason_code,
                    audited_input_hashes=audited_input_hashes,
                    trace_path=trace_path,
                )
        return AuditResult(
            layer=6,
            layer_name="Proof Checker",
            verdict=Verdict.ERROR,
            summary="Failed to parse proof-checker output",
            details={"theorems_audited": 0, "issues": []},
            method="parse_error",
            skill_name="proof-checker",
            session_id=session_id,
            policy_loaded=policy_loaded,
            model_name=model_name,
            reason_code="reviewer_error",
            audited_input_hashes=audited_input_hashes,
            trace_path=trace_path,
        )

    def _parse_audit_result(
        self,
        text: str,
        *,
        skill_name: str = "",
        session_id: str = "",
        policy_loaded: bool = False,
        model_name: str = "",
        trace_path: str = "",
    ) -> AuditResult:
        """解析审计结果 JSON and retain model/skill execution evidence."""
        from .draft_delivery import draft_blockers
        try:
            data = _extract_json_object(text, "verdict")
            if data:
                verdict_str = data.get("verdict", "ERROR").upper()
                verdict = Verdict(verdict_str) if verdict_str in Verdict.__members__ else Verdict.ERROR
                return AuditResult(
                    layer=0,
                    layer_name="",
                    verdict=verdict,
                    summary=data.get("summary", ""),
                    details=data.get("kill_memo", "") or data.get("adjudication", ""),
                    evidence=data.get("evidence", []),
                    skill_name=skill_name,
                    session_id=session_id,
                    policy_loaded=policy_loaded,
                    model_name=model_name,
                    trace_path=trace_path,
                    draft_blockers=draft_blockers(data.get("draft_blockers")),
                )
        except (json.JSONDecodeError, ValueError):
            pass

        return AuditResult(
            layer=0,
            layer_name="",
            verdict=Verdict.ERROR,
            summary="Failed to parse audit output",
            method="parse_error",
            skill_name=skill_name,
            session_id=session_id,
            policy_loaded=policy_loaded,
            model_name=model_name,
            trace_path=trace_path,
        )

    def _save_results(
        self, results: list[AuditResult], project_path: str,
        evidence_mode: str = "executed", *, run_id: str = "",
        expected_source_bundle_sha256: str = "",
        expected_audit_runtime_signature: str = "",
        expected_reviewer_route_sha256: str = "",
        expected_policy_sha256: dict[int, str] | None = None,
    ) -> None:
        from .audit_result_store import save_audit_results

        save_audit_results(
            results, project_path, evidence_mode, run_id=run_id,
            expected_source_bundle_sha256=expected_source_bundle_sha256,
            expected_audit_runtime_signature=expected_audit_runtime_signature,
            expected_reviewer_route_sha256=expected_reviewer_route_sha256,
            expected_policy_sha256=expected_policy_sha256,
            proof_detector=self._proof_detector_result,
        )
