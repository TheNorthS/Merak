"""Collect deterministic results findings for the risk coordinator.

Finding generation does not grant artifact acceptance. Repair responsibility
remains with the producer identified by each finding, not a downstream consumer."""

from __future__ import annotations
from pathlib import Path
from typing import Any
from .node_risk_audit import RESULT_ANALYSIS_BUILD_PATH, RESULT_ANALYSIS_BUILD_SCHEMA, _has_trusted_empirical_evidence, _workflow_evidence_mode
from .risk_artifact_support import _finding, _json, _missing, _relative, _sha256, _text
from .risk_constants import LIMITATION_RE, PENDING_RE, SIMULATION_SCOPE_RE, UNCERTAINTY_RE
from .risk_validator_support import _dict_list, _executed_result_data_files, _has_unbounded_supported_claim, _hash_mapping_digest, _ids, _load_csv_columns, _newest_mtime, _result_analysis_source_hashes, _result_data_files, _simulation_manifest_semantic_hash
from .simulation_policy import SIMULATION_STABLE_ROLES, simulation_manifest_contract_issues

class _EarlyReturn(BaseException):

    def __init__(self, value: Any):
        self.value = value

def _rule_1(options: Any, root: Any) -> dict[str, Any]:
    path = root / 'experiments' / 'results' / 'analysis.md'
    text = _text(path)
    if not text:
        raise _EarlyReturn([_missing('RESULT-ART-001', 'experiments/results/analysis.md')])
    findings: list[dict[str, Any]] = []
    evidence_mode = _workflow_evidence_mode(options)
    simulation_mode = evidence_mode == 'synthetic_preview'
    simulation_manifest_path: Path | None = None
    simulation_manifest: dict[str, Any] = {}
    simulation_manifest_data_paths: set[str] = set()
    simulation_manifest_files_current = False
    return {key: value for key, value in locals().items() if key in ['evidence_mode', 'findings', 'path', 'simulation_manifest', 'simulation_manifest_data_paths', 'simulation_manifest_files_current', 'simulation_manifest_path', 'simulation_mode', 'text']}

def _rule_2(findings: Any, options: Any, root: Any, simulation_manifest_data_paths: Any, simulation_mode: Any, text: Any) -> dict[str, Any]:
    if simulation_mode:
        manifest_path = root / 'experiments' / 'results' / 'simulated' / 'SIMULATION_MANIFEST.json'
        simulation_manifest_path = manifest_path
        manifest, manifest_error = _json(manifest_path)
        manifest = manifest if isinstance(manifest, dict) else {}
        if isinstance(manifest, dict):
            simulation_manifest = manifest
            data_records = _dict_list(manifest.get('data_files'))
            declared_data_paths: list[str] = []
            for record in data_records:
                relative = str(record.get('path') or '').strip()
                expected_hash = str(record.get('sha256') or '').strip()
                if not relative or not expected_hash:
                    continue
                candidate = (root / relative).resolve()
                try:
                    normalized = candidate.relative_to(root).as_posix()
                except ValueError:
                    continue
                if not normalized.startswith('experiments/results/simulated/') or not candidate.is_file() or _sha256(candidate) != expected_hash:
                    continue
                simulation_manifest_data_paths.add(normalized)
                declared_data_paths.append(normalized)
            required_data_paths = {'experiments/results/simulated/' + str(profile.get('data_file') or '').strip() for profile in _dict_list(manifest.get('domain_asset_profile')) if str(profile.get('stable_role') or '').strip() in SIMULATION_STABLE_ROLES and str(profile.get('data_file') or '').strip()}
            claim_contract = manifest.get('claim_evidence_contract')
            if isinstance(claim_contract, dict):
                claim_data_file = str(claim_contract.get('data_file') or '').strip()
                if claim_data_file:
                    required_data_paths.add(claim_data_file)
            simulation_manifest_files_current = bool(data_records) and len(declared_data_paths) == len(data_records) and (len(set(declared_data_paths)) == len(declared_data_paths)) and required_data_paths.issubset(simulation_manifest_data_paths)
        expected_roles = {'main_comparison', 'component_ablation', 'training_dynamics', 'robustness_sensitivity', 'error_analysis', 'calibration_risk_coverage', 'efficiency_tradeoff'}
        actual_roles = set(manifest.get('completeness_pack') or [])
        if manifest_error or not isinstance(manifest, dict) or simulation_manifest_contract_issues(manifest) or (manifest.get('evidence_status') != 'synthetic_preview') or (manifest.get('manuscript_eligible') is not True) or (not expected_roles.issubset(actual_roles)) or (not simulation_manifest_files_current):
            findings.append(_finding('RESULT-SIM-001', 'blocker', 'evidence_state', 'Deterministic benchmark manifest is missing, incomplete, or not submission-eligible.', '确定性固定基准清单缺失、不完整或没有标记为完整投稿证据。', ['experiments/results/simulated/SIMULATION_MANIFEST.json'], 'Regenerate the complete deterministic benchmark package before analysis.'))
        if not SIMULATION_SCOPE_RE.search(text):
            findings.append(_finding('RESULT-SIM-002', 'blocker', 'interpretation', 'Simulation result analysis does not bound its findings to a defined evaluation scope.', '仿真结果分析没有把结论限制在明确的评估范围内。', ['experiments/results/analysis.md'], 'State the simulator, controlled study, registered conditions, or evaluation domain and analyze only registered assets.'))
        # This is the internal evidence report, not a rendered manuscript.
        # Explicit preview disclosure (including the user's quoted direction)
        # must not prevent a hash-bound, scope-limited analysis from passing.
    elif not _has_trusted_empirical_evidence(options):
        if not PENDING_RE.search(text):
            findings.append(_finding('RESULT-MODE-001', 'blocker', 'evidence_state', 'Planned analysis does not explicitly say that experiments were not executed.', '结果分析没有明确写出实验未执行，读者可能把模板值误认为结果。', ['experiments/results/analysis.md'], 'Mark every claim PENDING and every number as schema/demo only.'))
        if _has_unbounded_supported_claim(text, current_method_only=True):
            findings.append(_finding('RESULT-MODE-002', 'blocker', 'overclaim', 'Planned analysis uses empirical support language without executed evidence.', '未运行实验的分析中出现了“显著优于/实验表明”等实证措辞，属于越界结论。', ['experiments/results/analysis.md'], 'Replace empirical conclusions with planned tests and rejection criteria.'))
    else:
        from .scientific_evidence import scientific_evidence_service
        valid, issues, _ = scientific_evidence_service.validate_executed_metrics(root)
        if not valid:
            for index, issue in enumerate(issues, start=1):
                findings.append(_finding(f'RESULT-PROV-{index:03d}', 'blocker', 'provenance', issue, f'结果无法追溯到成功运行：{issue}', ['experiments/results', '.merak/experiments'], 'Link every reported metric to an immutable run artifact.'))
    return {key: value for key, value in locals().items() if key in ['_', 'actual_roles', 'candidate', 'claim_contract', 'claim_data_file', 'data_records', 'declared_data_paths', 'expected_hash', 'expected_roles', 'index', 'issue', 'issues', 'manifest', 'manifest_error', 'manifest_path', 'normalized', 'record', 'relative', 'required_data_paths', 'scientific_evidence_service', 'simulation_manifest', 'simulation_manifest_files_current', 'simulation_manifest_path', 'valid']}

def _rule_3(evidence_mode: Any, findings: Any, options: Any, path: Any, root: Any, simulation_manifest: Any, simulation_manifest_data_paths: Any, simulation_manifest_files_current: Any, simulation_manifest_path: Any, simulation_mode: Any, text: Any) -> dict[str, Any]:
    selected, _ = _json(root / 'ideas' / 'SELECTED_IDEA.json')
    claim_ids = _ids(selected.get('claims')) if isinstance(selected, dict) else []
    missing_claims = [claim_id for claim_id in claim_ids if claim_id.casefold() not in text.casefold()]
    if missing_claims:
        findings.append(_finding('RESULT-CLAIM-001', 'warning', 'claim_mapping', f"Analysis does not mention frozen claim IDs: {', '.join(missing_claims)}", f"结果分析没有逐项处理冻结 claim：{', '.join(missing_claims)}，负结果或待验证项可能被遗漏。", ['ideas/SELECTED_IDEA.json', 'experiments/results/analysis.md'], 'Record each claim as supported, contradicted, or pending.'))
    if not UNCERTAINTY_RE.search(text) and (not (not simulation_mode and (not _has_trusted_empirical_evidence(options)) and PENDING_RE.search(text))):
        findings.append(_finding('RESULT-UNC-001', 'warning', 'statistics', 'Analysis does not report uncertainty or the independent analysis unit.', '结果分析没有说明置信区间、方差/效应量或独立分析单位，点估计可能被过度解读。', ['experiments/results/analysis.md', 'experiments/RUN_SPEC.json'], 'Report uncertainty at the correct independent unit and state the aggregation procedure.'))
    if (_has_trusted_empirical_evidence(options) or simulation_mode) and (not LIMITATION_RE.search(text)):
        findings.append(_finding('RESULT-FAIL-001', 'warning', 'interpretation', 'Analysis contains no failure cases, contrary evidence, or limitations.', '结果分析没有失败案例、反例或局限，容易只保留支持性结果。', ['experiments/results/analysis.md'], 'Add negative results, failure modes, and the claim consequences of each.'))
    if _has_trusted_empirical_evidence(options):
        metric_files, freshness_files = _executed_result_data_files(root)
    elif simulation_mode:
        metric_files = sorted((path for path in (root / 'experiments' / 'results' / 'simulated').glob('*.csv') if path.is_file() and path.stat().st_size > 0))
        freshness_files = [*metric_files, *([simulation_manifest_path] if simulation_manifest_path is not None and simulation_manifest_path.is_file() else [])]
    else:
        metric_files = _result_data_files(root, include_planned=False)
        freshness_files = metric_files
    simulation_content_bound = bool(simulation_mode and simulation_manifest_path is not None and simulation_manifest_files_current and simulation_manifest and (current_manifest_semantic_hash := _simulation_manifest_semantic_hash(simulation_manifest)) and (current_manifest_semantic_hash.casefold() in text.casefold() or _sha256(simulation_manifest_path).casefold() in text.casefold()) and {_relative(root, item) for item in metric_files}.issubset(simulation_manifest_data_paths))
    analysis_content_bound = False
    analysis_binding_stale = False
    changed_result_inputs: list[str] = []
    if _has_trusted_empirical_evidence(options):
        build, _ = _json(root / RESULT_ANALYSIS_BUILD_PATH)
        build = build if isinstance(build, dict) else {}
        current_source_hashes = _result_analysis_source_hashes(root, freshness_files)
        binding_applies = bool(build.get('schema') == RESULT_ANALYSIS_BUILD_SCHEMA and str(build.get('analysis_path') or '') == 'experiments/results/analysis.md' and (str(build.get('analysis_sha256') or '') == _sha256(path)) and (str(build.get('evidence_mode') or '') == evidence_mode))
        if binding_applies:
            recorded_source_hashes = dict(build.get('source_artifact_sha256') or {})
            analysis_content_bound = recorded_source_hashes == current_source_hashes and str(build.get('source_bundle_sha256') or '') == _hash_mapping_digest(current_source_hashes)
            if not analysis_content_bound:
                analysis_binding_stale = True
                changed_result_inputs = sorted((key for key in set(recorded_source_hashes) | set(current_source_hashes) if recorded_source_hashes.get(key) != current_source_hashes.get(key)))
    timestamp_stale = bool(freshness_files and (not simulation_content_bound) and (not analysis_content_bound) and (path.stat().st_mtime + 1.0 < _newest_mtime(freshness_files)))
    if analysis_binding_stale or timestamp_stale:
        finding = _finding('RESULT-STALE-001', 'blocker', 'freshness', 'Result analysis input hashes no longer match the current provenance-owned result artifacts.' if analysis_binding_stale else 'Result analysis is older than one or more machine-readable result artifacts.', 'analysis.md 绑定的原始结果哈希已经变化，现有结论分析的是旧实验。' if analysis_binding_stale else 'analysis.md 早于当前机器可读结果文件，现有结论可能分析的是旧实验。', ['experiments/results/analysis.md', RESULT_ANALYSIS_BUILD_PATH.as_posix(), *[_relative(root, item) for item in freshness_files[:8]]], 'Regenerate the analysis from the current owned result artifacts.')
        finding['freshness_basis'] = 'content_hashes' if analysis_binding_stale else 'mtime_fallback'
        finding['changed_inputs'] = changed_result_inputs
        findings.append(finding)
    return {key: value for key, value in locals().items() if key in ['_', 'analysis_binding_stale', 'analysis_content_bound', 'binding_applies', 'build', 'changed_result_inputs', 'claim_ids', 'current_manifest_semantic_hash', 'current_source_hashes', 'finding', 'freshness_files', 'metric_files', 'missing_claims', 'recorded_source_hashes', 'selected', 'simulation_content_bound', 'timestamp_stale']}

def _rule_4(findings: Any, metric_files: Any, options: Any, root: Any, simulation_mode: Any) -> dict[str, Any]:
    if _has_trusted_empirical_evidence(options) or simulation_mode:
        for metric_path in [item for item in metric_files if item.suffix.casefold() in {'.csv', '.tsv'}][:8]:
            columns, rows = _load_csv_columns(metric_path)
            if not columns or rows == 0:
                findings.append(_finding('RESULT-DATA-001', 'warning', 'data_integrity', f'Metric table is empty or unreadable: {_relative(root, metric_path)}', f'结果表 {_relative(root, metric_path)} 没有可读数据行，聚合分析可能忽略了失败输出。', [_relative(root, metric_path)], 'Repair or quarantine the table and record why the run produced no rows.'))
                continue
            normalized_columns = {item.casefold() for item in columns}
            if not normalized_columns.intersection({'seed', 'simulation_seed', 'run_id', 'subject', 'fold', 'replicate'}):
                findings.append(_finding('RESULT-DATA-002', 'warning', 'statistics', f'Metric table has no independent-unit identifier: {_relative(root, metric_path)}', f'结果表 {_relative(root, metric_path)} 缺少 seed/run_id/subject/fold 等独立单位字段，统计检验可能把相关样本当作独立样本。', [_relative(root, metric_path)], 'Include the independent experimental unit in machine-readable outputs.'))
    return {key: value for key, value in locals().items() if key in ['columns', 'metric_path', 'normalized_columns', 'rows']}

def audit(service: Any, root: Path, options: dict[str, Any]) -> list[dict[str, Any]]:
    state = {'root': root, 'service': service, 'options': options}
    try:
        state.update(_rule_1(options=state['options'], root=state['root']))
        state.update(_rule_2(findings=state['findings'], options=state['options'], root=state['root'], simulation_manifest_data_paths=state['simulation_manifest_data_paths'], simulation_mode=state['simulation_mode'], text=state['text']))
        state.update(_rule_3(evidence_mode=state['evidence_mode'], findings=state['findings'], options=state['options'], path=state['path'], root=state['root'], simulation_manifest=state['simulation_manifest'], simulation_manifest_data_paths=state['simulation_manifest_data_paths'], simulation_manifest_files_current=state['simulation_manifest_files_current'], simulation_manifest_path=state['simulation_manifest_path'], simulation_mode=state['simulation_mode'], text=state['text']))
        state.update(_rule_4(findings=state['findings'], metric_files=state['metric_files'], options=state['options'], root=state['root'], simulation_mode=state['simulation_mode']))
    except _EarlyReturn as returned:
        return returned.value
    return state.get('findings', [])
