"""Validate planned and immutable executed-run records without launching jobs."""
from __future__ import annotations
from pathlib import Path
from typing import Any
from .node_risk_audit import _training_check_findings, _workflow_evidence_mode
from .risk_artifact_support import _finding, _json, _missing, _relative
from .risk_validator_support import _artifact_files, _dict_list, _result_data_files

def _planned_status_findings(manifest: dict[str, Any], evidence_mode: str) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    expected_status = 'synthetic_preview' if evidence_mode == 'synthetic_preview' else 'planned_not_executed'
    manifest_status = str(manifest.get('status') or '')
    if manifest_status != expected_status:
        findings.append(_finding('RUN-PLANNED-002', 'blocker', 'evidence_state', f'No-run manifest status does not match the selected evidence mode: expected {expected_status!r}, got {manifest_status!r}.', '用户选择不运行实验，但计划产物状态与所选证据模式不一致，可能被误当成真实证据。', ['experiments/results/templates/PLANNED_RESULT_MANIFEST.json'], 'Restore the explicit status required by the selected no-experiment evidence mode.'))
    if str(manifest.get('evidence_mode') or '').casefold() != evidence_mode:
        findings.append(_finding('RUN-PLANNED-004', 'blocker', 'evidence_state', 'No-run manifest evidence_mode does not match the workflow selection.', '计划产物的 evidence_mode 与工作流选择不一致，无法可靠区分预览和科研证据。', ['experiments/results/templates/PLANNED_RESULT_MANIFEST.json'], 'Regenerate the templates using the workflow-selected evidence mode.'))
    if evidence_mode == 'synthetic_preview' and manifest.get('manuscript_eligible') is not True:
        findings.append(_finding('RUN-PLANNED-005', 'blocker', 'evidence_state', 'Selected scenario manifest is not manuscript-eligible.', '模拟场景清单没有声明可用于草稿。', ['experiments/results/templates/PLANNED_RESULT_MANIFEST.json'], 'Require manuscript_eligible=true with current provenance; synthetic scenarios remain submission_eligible=false.'))
    return findings

def _audit_no_run(root: Path, options: dict[str, Any]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    manifest_path = root / 'experiments' / 'results' / 'templates' / 'PLANNED_RESULT_MANIFEST.json'
    manifest, error = _json(manifest_path)
    if error or not isinstance(manifest, dict):
        return [_missing('RUN-PLANNED-001', 'experiments/results/templates/PLANNED_RESULT_MANIFEST.json')]
    evidence_mode = _workflow_evidence_mode(options)
    findings = _planned_status_findings(manifest, evidence_mode)
    existing_metrics = _result_data_files(root, include_planned=False)
    if existing_metrics and evidence_mode != 'synthetic_preview':
        findings.append(_finding('RUN-PLANNED-003', 'warning', 'evidence_state', 'Executed-looking result files already exist while this workflow is in no-run mode.', '当前工作流选择不运行实验，但项目中已有看似真实的结果文件；必须明确它们属于哪个历史运行，不能自动沿用。', [_relative(root, path) for path in existing_metrics[:8]], 'Bind reusable results to an immutable prior run or quarantine them from the planned workflow.'))
    return findings

def _completed_manifest_findings(root: Path, path: Path, payload: dict[str, Any]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    missing_runtime_fields = [name for name in ('result_artifacts', 'config_hashes', 'attempts') if not payload.get(name)]
    if missing_runtime_fields:
        findings.append(_finding('RUN-MANIFEST-001', 'blocker', 'provenance', f"Completed run manifest lacks: {', '.join(missing_runtime_fields)}.", f"已完成运行 {path.parent.name} 缺少 {', '.join(missing_runtime_fields)}，无法证明结果来自哪份代码和配置。", [path.relative_to(root).as_posix()], 'Finalize the managed run with config hashes, attempt history, and owned result artifacts.'))
    attempts = _dict_list(payload.get('attempts'))
    current_attempt = int(payload.get('current_attempt') or 0)
    final_attempt = next((item for item in attempts if int(item.get('attempt') or 0) == current_attempt), {})
    if final_attempt and (not final_attempt.get('finished_at')):
        findings.append(_finding('RUN-MANIFEST-002', 'blocker', 'provenance', 'Completed run has no finished_at on its final attempt.', f'运行 {path.parent.name} 标记 completed，但最终 attempt 没有结束时间，状态不一致。', [path.relative_to(root).as_posix()], 'Repair the scheduler finalization record before accepting its metrics.'))
    critical_anomalies = [item for item in _dict_list(payload.get('anomalies')) if str(item.get('severity') or '').casefold() == 'critical']
    if critical_anomalies:
        findings.append(_finding('RUN-HEALTH-001', 'blocker', 'runtime_health', 'Run is marked completed despite preserved critical health anomalies.', f'运行 {path.parent.name} 同时标记完成和 critical anomaly，不能直接进入结果分析。', [path.relative_to(root).as_posix()], 'Quarantine the run, diagnose the anomaly, and rerun or explicitly adjudicate it.'))
    return findings

def _runtime_manifest_findings(root: Path, manifests: list[Path]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for path in manifests:
        payload, _ = _json(path)
        if not isinstance(payload, dict):
            continue
        if payload.get('evidence_eligible') is False or payload.get('submission_eligible') is False:
            continue
        if str(payload.get('status') or '') in {'failed', 'anomaly_stopped', 'cancelled'}:
            findings.append(_finding('RUN-STATE-001', 'warning', 'runtime', f"Preserved runtime attempt is not successful: {path.parent.name}={payload.get('status')}", f"保留的实验 {path.parent.name} 状态为 {payload.get('status')}；分析时必须排除或解释该 attempt。", [path.relative_to(root).as_posix()], 'Keep it for diagnosis but exclude it from accepted aggregates.'))
        if str(payload.get('status') or '') == 'completed':
            findings.extend(_completed_manifest_findings(root, path, payload))
    log_files = _artifact_files(root / 'experiments' / 'logs', {'.log', '.txt', '.jsonl'})
    if not log_files:
        findings.append(_finding('RUN-LOG-001', 'warning', 'runtime', 'No persistent experiment log was found for an executed workflow.', '执行模式下没有保留训练日志；即使指标存在，也难以检查收敛、异常和早停过程。', ['experiments/logs'], 'Persist stdout/stderr or structured metrics for every accepted attempt.'))
    return findings

def audit(service: Any, root: Path, options: dict[str, Any]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    if options.get('run_experiment') is not True:
        return [*_audit_no_run(root, options), *_training_check_findings(options)]
    training_findings = _training_check_findings(options)
    if training_findings:
        return training_findings
    from .scientific_evidence import scientific_evidence_service
    valid, issues, _ = scientific_evidence_service.validate_executed_metrics(root)
    if not valid:
        for index, issue in enumerate(issues, start=1):
            findings.append(_finding(f'RUN-PROV-{index:03d}', 'blocker', 'provenance', issue, f'实验执行证据不完整：{issue}', ['experiments/results', '.merak/execution_events.jsonl', '.merak/experiments'], 'Preserve a successful immutable run and hash-link its result artifacts.'))
    manifests = sorted((root / '.merak' / 'experiments').glob('*/run.json')) if (root / '.merak' / 'experiments').is_dir() else []
    findings.extend(_runtime_manifest_findings(root, manifests))
    return findings
