"""Validate structured review outcomes and compiled-PDF source identity."""
from __future__ import annotations
from pathlib import Path
from typing import Any
import hashlib
from .node_risk_audit import _has_trusted_empirical_evidence, _workflow_evidence_mode
from .risk_artifact_support import _finding, _json, _missing, _relative
from .risk_validator_support import _dict_list, _newest_mtime, _string_list
from dataclasses import dataclass

@dataclass(frozen=True)
class ReviewSourceIdentity:
    findings: list[dict[str, Any]]
    source_hash: str

@dataclass(frozen=True)
class ReviewRoundLimits:
    current_round: int
    max_rounds: int

def _source_identity(root: Path, path: Path, state: dict[str, Any], managed_review: bool) -> ReviewSourceIdentity:
    findings: list[dict[str, Any]] = []
    current_hash = ''
    reviewed_inputs = [root / relative for relative in ('paper/main.tex', 'ideas/SELECTED_IDEA.json', 'experiments/results/analysis.md', 'figures/SCIENTIFIC_ASSET_PLAN.json', 'figures/FIGURE_MANIFEST.json')]
    recorded_source_hash = str(state.get('source_bundle_sha256') or '')
    if not recorded_source_hash and path.stat().st_mtime + 1.0 < _newest_mtime(reviewed_inputs):
        findings.append(_finding('REVIEW-STALE-001', 'blocker', 'freshness', 'A reviewed paper, claim, result, or figure artifact changed after REVIEW_STATE.json was finalized.', '论文、冻结 claim、结果或图表在审稿状态落盘后发生了修改，旧审稿结论不能认证当前版本。', ['review-stage/REVIEW_STATE.json', *[_relative(root, item) for item in reviewed_inputs if item.is_file()]], 'Run a fresh bounded review against the current research bundle.'))
    if managed_review:
        from ..workflows.review_audit import review_source_bundle
        current_hash, _ = review_source_bundle(root)
        if not recorded_source_hash or recorded_source_hash != current_hash:
            findings.append(_finding('REVIEW-HASH-001', 'blocker', 'freshness', 'Structured review is not hash-bound to the current research source bundle.', '结构化审稿记录的来源哈希与当前论文、Idea、结果或图表不一致。', ['review-stage/REVIEW_STATE.json', 'paper/main.tex'], 'Rerun the bounded review and persist the current source bundle hash.'))
    return ReviewSourceIdentity(findings, current_hash)

def _visual_review_complete(final: dict[str, Any], managed_review: bool) -> bool:
    required_visual_fields = {'pdf_path', 'figure_quality', 'caption_alignment', 'page_layout', 'table_formatting', 'visual_consistency'}
    visual_review = final.get('visual_review') if isinstance(final.get('visual_review'), dict) else {}
    visual_review_complete = bool(not managed_review or (required_visual_fields.issubset(visual_review) and all((str(visual_review.get(key) or '').strip() for key in required_visual_fields))))
    return visual_review_complete

def _visual_review_findings(managed_review: bool, visual_review_complete: bool) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    if managed_review and (not visual_review_complete):
        findings.append(_finding('REVIEW-PDF-VISUAL-001', 'blocker', 'review_integrity', 'The final managed review does not attest inspection of the freshly compiled PDF layout.', '最终原生审稿没有完整记录对本轮编译 PDF 的视觉与版式检查。', ['review-stage/REVIEW_STATE.json', 'paper/main.pdf'], 'Rerun the independent review against the compiled PDF and persist every visual_review field.'))
    return findings

def _final_round_findings(state: dict[str, Any], rounds: list[dict[str, Any]]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    final = rounds[-1]
    weaknesses = _string_list(final.get('weaknesses'))
    actions = _string_list(final.get('action_items'))
    declared_final_verdict = str(final.get('verdict') or state.get('final_verdict') or '').replace('-', '_').replace(' ', '_').casefold()
    if not weaknesses and (not actions) and (declared_final_verdict not in {'ready', 'almost'}):
        findings.append(_finding('REVIEW-STATE-003', 'blocker', 'review_integrity', 'Final review round records neither weaknesses nor action items.', '最终审稿轮次没有弱点或处理项，无法证明进行了实质审查。', ['review-stage/REVIEW_STATE.json'], 'Record substantive objections and how each was resolved or left open.'))
    return findings

def _round_sequence_findings(rounds: list[dict[str, Any]]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    final = rounds[-1]
    round_numbers = [int(item.get('round') or 0) for item in rounds]
    if round_numbers != list(range(1, len(rounds) + 1)):
        findings.append(_finding('REVIEW-STATE-004', 'blocker', 'review_integrity', f'Review round sequence is invalid: {round_numbers}', f'审稿轮次序列不连续：{round_numbers}，无法确认当前结论来自哪一轮修订。', ['review-stage/REVIEW_STATE.json'], 'Persist consecutive rounds starting at 1 and retain their findings/actions.'))
    parse_failures = [item for item in rounds if any(('unable to parse' in value.casefold() for value in _string_list(item.get('weaknesses'))))]
    if parse_failures:
        final_round_failed = final in parse_failures
        has_valid_round = any((item not in parse_failures for item in rounds))
        parse_failure_blocks = final_round_failed or not has_valid_round
        findings.append(_finding('REVIEW-PARSE-001', 'blocker' if parse_failure_blocks else 'warning', 'review_integrity', 'The final review outcome is a parser fallback rather than a structured review.' if parse_failure_blocks else 'An earlier review round used a parser fallback; later structured rounds remain auditable.', '最终审稿结论只是结构化解析失败的兜底记录，不能据此认证当前结论。' if parse_failure_blocks else '较早一轮审稿解析失败，但后续结构化轮次有效；保留为审稿完整性警告。', ['review-stage/REVIEW_STATE.json'], 'Rerun the final review round and persist valid structured findings.' if parse_failure_blocks else 'Retain the failed-round trace and use the later structured findings as the bounded outcome.'))
    return findings

def _evidence_mode_findings(state: dict[str, Any], options: dict[str, Any]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    expected_mode = _workflow_evidence_mode(options)
    evidence_mode = str(state.get('evidence_mode') or '').strip().casefold()
    if evidence_mode and evidence_mode != expected_mode:
        findings.append(_finding('REVIEW-MODE-001', 'blocker', 'evidence_state', f'Review evidence mode is {evidence_mode}, expected {expected_mode}.', f'审稿按 {evidence_mode} 证据模式执行，但当前工作流是 {expected_mode} 模式，评分口径不一致。', ['review-stage/REVIEW_STATE.json'], 'Rerun the bounded review using the current experiment-execution mode.'))
    if not _has_trusted_empirical_evidence(options) and bool(state.get('publication_ready')):
        findings.append(_finding('REVIEW-MODE-002', 'blocker', 'overclaim', 'A planned/no-experiment manuscript is marked publication-ready.', '实验未运行，但审稿状态把稿件标记为可投稿，混淆了阶段就绪与科研证据成熟度。', ['review-stage/REVIEW_STATE.json', 'paper/main.tex'], 'Keep publication_ready=false until provenance-backed experiments and audits exist.'))
    return findings

def _round_limits(state: dict[str, Any], rounds: list[dict[str, Any]]) -> ReviewRoundLimits:
    try:
        current_round = int(state.get('current_round') or len(rounds))
        max_rounds = int(state.get('max_rounds') or 0)
    except (TypeError, ValueError):
        current_round = len(rounds)
        max_rounds = 0
    return ReviewRoundLimits(current_round, max_rounds)

def _outcome_findings(state: dict[str, Any], options: dict[str, Any], rounds: list[dict[str, Any]], visual_review_complete: bool, limits: ReviewRoundLimits) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    final_score = state.get('final_score')
    final_verdict = str(state.get('final_verdict') or '').replace('-', '_').replace(' ', '_').lower()
    try:
        score_ok = float(final_score) >= 6
    except (TypeError, ValueError):
        score_ok = False
    threshold_met = score_ok and final_verdict in {'ready', 'almost'} and visual_review_complete
    current_round = limits.current_round
    max_rounds = limits.max_rounds
    bounded_complete = bool(state.get('bounded_complete') or threshold_met or state.get('is_complete') or (max_rounds > 0 and current_round >= max_rounds and (len(rounds) >= max_rounds)))
    draft = options.get("delivery_goal") == state.get("delivery_goal") == "reviewable_draft"
    advisory_outcome = bool((draft or not _has_trusted_empirical_evidence(options)) and bounded_complete)
    if not threshold_met:
        findings.append(_finding('REVIEW-OUTCOME-001', 'warning' if advisory_outcome else 'blocker', 'review_outcome', f"Structured final review outcome is not accepted: score={final_score}, verdict={final_verdict or 'unknown'}.", f"有限审稿已完成但未达评分门槛：score={final_score}，verdict={final_verdict or 'unknown'}。当前仅作为非实证阶段警告，投稿资格保持关闭。" if advisory_outcome else f"结构化审稿结论未达门槛：score={final_score}，verdict={final_verdict or 'unknown'}。", ['review-stage/REVIEW_STATE.json'], 'Carry the unresolved findings into the downstream audit and keep publication_ready=false.' if advisory_outcome else 'Resolve critical findings or preserve the node as awaiting revision.'))
    reviewer = str(state.get('reviewer_model') or '').strip()
    if not reviewer:
        findings.append(_finding('REVIEW-MODEL-001', 'warning', 'independence', 'Review state does not identify the reviewer model.', '审稿状态没有记录 reviewer 模型，无法审计是否为独立审稿。', ['review-stage/REVIEW_STATE.json'], 'Persist executor and reviewer provider/model identities.'))
    return findings

def _final_snapshot_issues(root: Path, final_snapshot: dict[str, Any] | None, current_hash: str) -> list[str]:
    snapshot_issues: list[str] = []
    if final_snapshot is not None:
        snapshot_path = (root / str(final_snapshot.get('snapshot_path') or '')).resolve()
        report_path = (root / str(final_snapshot.get('layout_report_path') or '')).resolve()
        try:
            snapshot_path.relative_to(root)
            report_path.relative_to(root)
        except ValueError:
            snapshot_issues.append('snapshot/report path leaves the project')
        else:
            if not snapshot_path.is_file() or snapshot_path.stat().st_size <= 0 or snapshot_path.read_bytes()[:5] != b'%PDF-':
                snapshot_issues.append('final round PDF is missing or invalid')
            elif str(final_snapshot.get('pdf_sha256') or '') != hashlib.sha256(snapshot_path.read_bytes()).hexdigest():
                snapshot_issues.append('final round PDF hash does not match')
            if not report_path.is_file():
                snapshot_issues.append('final PDF layout report is missing')
            if str(final_snapshot.get('source_bundle_sha256') or '') != current_hash:
                snapshot_issues.append('final PDF snapshot is stale relative to current sources')
    return snapshot_issues

def _snapshot_findings(root: Path, state: dict[str, Any], current_hash: str, current_round: int) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    snapshots = _dict_list(state.get('pdf_snapshots'))
    snapshot_rounds = {int(item.get('round') or 0) for item in snapshots if str(item.get('round') or '0').lstrip('-').isdigit()}
    expected_snapshot_rounds = set(range(0, max(0, current_round) + 1))
    missing_snapshot_rounds = sorted(expected_snapshot_rounds - snapshot_rounds)
    if missing_snapshot_rounds:
        findings.append(_finding('REVIEW-PDF-SNAPSHOT-001', 'blocker', 'review_integrity', 'Managed review is missing compiled PDF snapshots for rounds ' + ', '.join((str(value) for value in missing_snapshot_rounds)) + '.', '原生审稿缺少原稿或轮次 PDF 快照，无法比较修改前后版本。', ['review-stage/REVIEW_STATE.json', 'paper/'], 'Recompile and preserve main_round0_original.pdf plus every main_roundN.pdf.'))
    final_snapshot = next((item for item in reversed(snapshots) if str(item.get('round') or '0').lstrip('-').isdigit() and int(item.get('round') or 0) == current_round), None)
    snapshot_issues = _final_snapshot_issues(root, final_snapshot, current_hash)
    if snapshot_issues:
        findings.append(_finding('REVIEW-PDF-SNAPSHOT-002', 'blocker', 'freshness', '; '.join(snapshot_issues), '最终审稿 PDF、版式报告或来源哈希不完整/已过期。', ['review-stage/REVIEW_STATE.json', 'paper/main.pdf'], 'Recompile the reconciled manuscript and refresh the final numbered PDF snapshot.'))
    return findings

def _round_bound_findings(state: dict[str, Any], rounds: list[dict[str, Any]]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    max_rounds = int(state.get('max_rounds') or len(rounds))
    if max_rounds > 4:
        findings.append(_finding('REVIEW-BOUND-001', 'warning', 'review_integrity', f'Review state allows {max_rounds} internal rounds.', '审稿内部轮次超过 4，容易形成无界模型互改；应在有限轮次后交给研究者判断。', ['review-stage/REVIEW_STATE.json'], 'Cap automatic review at four rounds and require explicit researcher feedback for another cycle.'))
    return findings

def audit(service: Any, root: Path, options: dict[str, Any]) -> list[dict[str, Any]]:
    path = root / 'review-stage' / 'REVIEW_STATE.json'
    state, error = _json(path)
    if error or not isinstance(state, dict):
        return [_missing('REVIEW-STATE-001', 'review-stage/REVIEW_STATE.json')]
    managed_review = str(state.get('managed_by') or '') == 'cross_model_review_loop'
    identity = _source_identity(root, path, state, managed_review)
    findings = identity.findings
    rounds = _dict_list(state.get('rounds'))
    if not rounds:
        findings.append(_finding('REVIEW-STATE-002', 'blocker', 'review_integrity', 'Review state has no structured review rounds; a printed score is not evidence of review.', '审稿状态没有结构化轮次；模型在正文里自报分数不能作为通过依据。', ['review-stage/REVIEW_STATE.json'], 'Persist reviewer findings, actions, and final outcome for at least one round.'))
        return findings
    visual = _visual_review_complete(rounds[-1], managed_review)
    limits = _round_limits(state, rounds)
    findings.extend(_visual_review_findings(managed_review, visual))
    findings.extend(_final_round_findings(state, rounds))
    findings.extend(_round_sequence_findings(rounds))
    findings.extend(_evidence_mode_findings(state, options))
    findings.extend(_outcome_findings(state, options, rounds, visual, limits))
    if managed_review:
        findings.extend(_snapshot_findings(root, state, identity.source_hash, limits.current_round))
    findings.extend(_round_bound_findings(state, rounds))
    return findings
