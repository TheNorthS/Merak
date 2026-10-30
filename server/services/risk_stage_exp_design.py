"""Collect deterministic exp design findings for the risk coordinator.

Finding generation does not grant artifact acceptance. Repair responsibility
remains with the producer identified by each finding, not a downstream consumer."""

from __future__ import annotations
from pathlib import Path
from typing import Any
import ast
import re
from .node_risk_audit import _reachable_python_placeholders, _run_spec_command, _workflow_evidence_mode
from .risk_artifact_support import _finding, _json, _missing, _text
from .risk_validator_support import _artifact_files, _placeholder_excerpt
from .run_spec import run_spec_requires_seeds, run_spec_seed_groups, unresolved_command_placeholders

class _EarlyReturn(BaseException):

    def __init__(self, value: Any):
        self.value = value

def _rule_1(options: Any, root: Any) -> dict[str, Any]:
    from .experiment_implementation import experiment_implementation_service
    from .method_contract import method_contract_service
    findings: list[dict[str, Any]] = []
    selected, selected_error = _json(root / 'ideas' / 'SELECTED_IDEA.json')
    title = str(selected.get('title') or '') if isinstance(selected, dict) else ''
    if selected_error:
        findings.append(_missing('DESIGN-UPSTREAM-001', 'ideas/SELECTED_IDEA.json'))
    evidence_mode = _workflow_evidence_mode(options)
    allow_planned = options.get('run_experiment') is not True and evidence_mode != 'synthetic_preview'
    valid, issues, _ = method_contract_service.validate_method_contract(root, title, allow_planned=allow_planned)
    if not valid:
        for index, issue in enumerate(issues[:20], start=1):
            findings.append(_finding(f'DESIGN-CONTRACT-{index:03d}', 'blocker', 'implementation', issue, f'实验设计与冻结 Idea 未对齐：{issue}', ['experiments/METHOD_CONTRACT.json', 'experiments/src', 'experiments/configs'], 'Repair the declared implementation evidence; do not weaken the accepted mechanism.'))
    implementation_audit = experiment_implementation_service.audit(root)
    for item in implementation_audit.get('findings', []):
        if not isinstance(item, dict):
            continue
        severity = 'blocker' if str(item.get('severity') or '').casefold() in {'blocker', 'critical', 'error', 'fail'} else 'warning'
        if str(item.get('id') or '').startswith('IMPL-CONFIG-PROBE-') and options.get('run_experiment') is not True:
            severity = 'warning'
        evidence = item.get('target_files') or item.get('evidence') or []
        if isinstance(evidence, str):
            evidence = [evidence]
        finding = _finding(str(item.get('id') or 'DESIGN-IMPLEMENTATION-INTEGRITY'), severity, str(item.get('category') or 'implementation'), str(item.get('message') or 'Experiment implementation integrity check failed.'), str(item.get('plain_message') or item.get('message') or '实验实现完整性检查未通过。'), [str(value) for value in evidence if str(value).strip()] or ['experiments/src', 'experiments/RUN_SPEC.json'], str(item.get('remediation') or 'Implement the complete reachable experiment execution path.'))
        finding['owner_node'] = 'exp-design'
        finding['upstream_node'] = 'exp-design'
        findings.append(finding)
    if (root / 'experiments' / 'IMPLEMENTATION_BLUEPRINT.json').is_file() or (root / 'experiments' / 'IMPLEMENTATION_BUILD.json').is_file():
        from .experiment_implementation_build import experiment_implementation_build_service
        build_audit = experiment_implementation_build_service.audit(root, title)
        for stage_report in build_audit.get('stages', []):
            if not isinstance(stage_report, dict):
                continue
            stage_id = str(stage_report.get('stage_id') or 'unknown')
            targets = [str(item) for item in stage_report.get('targets', []) if str(item).strip()]
            for index, issue in enumerate(stage_report.get('issues', [])[:12], start=1):
                finding = _finding(f'DESIGN-STAGE-{stage_id.upper()}-{index:03d}', 'blocker', 'staged_implementation', f'Implementation stage {stage_id} is incomplete: {issue}', f'分阶段实现的 {stage_id} 阶段未通过：{issue}', targets or ['experiments/IMPLEMENTATION_BUILD.json'], 'Repair only this implementation stage, pass its deterministic gate, then rebuild downstream stages.')
                finding['owner_node'] = 'exp-design'
                finding['upstream_node'] = 'exp-design'
                findings.append(finding)
    run_spec, error = _json(root / 'experiments' / 'RUN_SPEC.json')
    command_files: list[Path] = []
    return {key: value for key, value in locals().items() if key in ['_', 'allow_planned', 'build_audit', 'command_files', 'error', 'evidence', 'evidence_mode', 'experiment_implementation_build_service', 'experiment_implementation_service', 'finding', 'findings', 'implementation_audit', 'index', 'issue', 'issues', 'item', 'method_contract_service', 'run_spec', 'selected', 'selected_error', 'severity', 'stage_id', 'stage_report', 'targets', 'title', 'valid']}

def _rule_2(command_files: Any, error: Any, findings: Any, options: Any, root: Any, run_spec: Any) -> dict[str, Any]:
    if error or not isinstance(run_spec, dict):
        findings.append(_missing('DESIGN-RUN-001', 'experiments/RUN_SPEC.json'))
    else:
        run_experiment = options.get('run_experiment') is True
        command = _run_spec_command(run_spec, run_experiment=run_experiment)
        if not command:
            findings.append(_finding('DESIGN-RUN-002', 'blocker', 'execution', 'RUN_SPEC.command is empty.', 'RUN_SPEC.json 没有可执行命令，实验部署节点无法启动。', ['experiments/RUN_SPEC.json'], 'Declare one project-relative training command.'))
        else:
            unresolved_placeholders = unresolved_command_placeholders(command)
            if unresolved_placeholders:
                findings.append(_finding('DESIGN-RUN-005', 'blocker', 'execution', 'RUN_SPEC command contains unresolved placeholder(s): ' + ', '.join(unresolved_placeholders), 'RUN_SPEC 正式命令仍含运行时无法解析的占位符：' + '、'.join(unresolved_placeholders), ['experiments/RUN_SPEC.json'], 'Bind arguments to project files/configuration or use only the scheduler placeholders {seed}, {batch_size}, and {work_dir}.'))
            command_paths = re.findall('(?:^|\\s)[\\"\']?([^\\s\\"\']+\\.(?:py|yaml|yml|json|toml|sh|ps1))[\\"\']?', command, re.IGNORECASE)
            for raw_path in command_paths[:8]:
                declared = Path(raw_path)
                candidate = declared if declared.is_absolute() else root / declared
                try:
                    candidate.resolve().relative_to(root)
                except (OSError, ValueError):
                    findings.append(_finding('DESIGN-RUN-003', 'blocker', 'execution', f'RUN_SPEC command references a path outside the project: {raw_path}', f'RUN_SPEC 命令引用了项目外路径 {raw_path}，远程同步和复现时无法保证使用同一代码。', ['experiments/RUN_SPEC.json'], 'Use a project-relative script/config path and declare external data separately.'))
                    continue
                if not candidate.is_file():
                    findings.append(_finding('DESIGN-RUN-004', 'blocker', 'execution', f'RUN_SPEC command references a missing file: {raw_path}', f'RUN_SPEC 命令引用的文件 {raw_path} 不存在，实验无法按声明启动。', ['experiments/RUN_SPEC.json', raw_path], 'Create the declared script/config or correct the command.'))
                else:
                    command_files.append(candidate.resolve())
        if run_experiment:
            execution_mode = str(run_spec.get('execution_mode') or '').strip().casefold()
            if execution_mode and re.search('(?:code.?check|dry.?run|scaffold|planned|no.?run)', execution_mode):
                findings.append(_finding('DESIGN-EXEC-001', 'blocker', 'execution', f'RUN_SPEC execution_mode={execution_mode!r} is not a scientific execution mode.', f'用户要求运行实验，但 RUN_SPEC.execution_mode={execution_mode!r} 仍是检查/脚手架模式。', ['experiments/RUN_SPEC.json'], 'Declare an executable training mode and keep dry-run as a separate preflight command.'))
            if run_spec.get('do_not_run_scientific_training') is True:
                findings.append(_finding('DESIGN-EXEC-002', 'blocker', 'execution', 'RUN_SPEC explicitly forbids scientific training.', '用户要求运行实验，但 RUN_SPEC 明确禁止 scientific training。', ['experiments/RUN_SPEC.json'], 'Implement and approve the real runner before entering exp-run.'))
            if re.search('(?:^|\\s)--dry-run(?:\\s|$)', command):
                findings.append(_finding('DESIGN-EXEC-003', 'blocker', 'execution', 'RUN_SPEC.command invokes --dry-run instead of scientific training.', '正式实验命令仍带有 --dry-run，只会检查代码而不会产生科研证据。', ['experiments/RUN_SPEC.json'], 'Move --dry-run to preflight_command and provide a separate real command.'))
            for candidate in command_files:
                if candidate.suffix.casefold() in {'.yaml', '.yml', '.json', '.toml', '.ini', '.cfg'}:
                    config_text = _text(candidate)
                    enabled_flags = sorted(set((match.group(1) for match in re.finditer('(?im)^\\s*(code_check_only|dry_run|scaffold_only|implementation_status)\\s*[:=]\\s*(?:true|1|yes|scaffold[^\\r\\n]*|code.?check[^\\r\\n]*|planned[^\\r\\n]*)\\b', config_text))))
                    if enabled_flags:
                        findings.append(_finding('DESIGN-EXEC-004', 'blocker', 'execution', 'Real-run config still enables non-execution flags: ' + ', '.join(enabled_flags), '正式实验配置仍开启检查/脚手架标志：' + '、'.join(enabled_flags), [candidate.relative_to(root).as_posix()], 'Create an execution config with these flags disabled; do not mutate dry-run provenance.'))
                if candidate.suffix.casefold() == '.py':
                    placeholders = _reachable_python_placeholders(candidate)
                    if placeholders:
                        findings.append(_finding('DESIGN-EXEC-005', 'blocker', 'implementation', 'Declared entrypoint reaches unfinished code: ' + '; '.join(placeholders[:6]), '正式实验入口仍可达未实现代码：' + '；'.join(placeholders[:6]), [candidate.relative_to(root).as_posix()], 'Implement the reachable training path and test it with a bounded real-data smoke run.'))
        seed_groups = run_spec_seed_groups(run_spec)
        if not seed_groups and run_spec_requires_seeds(run_spec):
            findings.append(_finding('DESIGN-REP-001', 'warning', 'reproducibility', 'RUN_SPEC has no explicit seed list.', 'RUN_SPEC.json 没有明确随机种子列表，无法区分单次调试和正式多次实验。', ['experiments/RUN_SPEC.json'], 'Declare the planned seeds and failed-seed policy.'))
        else:
            duplicate_groups = [name for name, seeds in seed_groups.items() if len({str(item) for item in seeds}) != len(seeds)]
            if duplicate_groups:
                findings.append(_finding('DESIGN-REP-002', 'warning', 'reproducibility', 'RUN_SPEC contains duplicate seed values in group(s): ' + ', '.join(duplicate_groups), 'RUN_SPEC 的部分随机种子组内存在重复值，会把重复运行误计为独立重复。', ['experiments/RUN_SPEC.json'], 'Use unique seeds within each declared group and state how failed seeds are handled.'))
    return {key: value for key, value in locals().items() if key in ['candidate', 'command', 'command_paths', 'config_text', 'declared', 'duplicate_groups', 'enabled_flags', 'execution_mode', 'placeholders', 'raw_path', 'run_experiment', 'seed_groups', 'unresolved_placeholders']}

def _rule_3(findings: Any, root: Any) -> dict[str, Any]:
    source_files = sorted((root / 'experiments' / 'src').rglob('*.py')) if (root / 'experiments' / 'src').is_dir() else []
    if not source_files:
        findings.append(_missing('DESIGN-CODE-001', 'experiments/src'))
    for path in source_files:
        try:
            ast.parse(path.read_text(encoding='utf-8-sig', errors='strict'), filename=str(path))
        except (OSError, UnicodeError, SyntaxError) as exc:
            findings.append(_finding('DESIGN-CODE-002', 'blocker', 'implementation', f'Experiment source cannot be parsed: {path.relative_to(root).as_posix()}: {exc}', f'实验代码 {path.relative_to(root).as_posix()} 无法解析：{exc}', [path.relative_to(root).as_posix()], 'Fix the source syntax before deployment.'))
    config_files = _artifact_files(root / 'experiments' / 'configs', {'.yaml', '.yml', '.json', '.toml', '.ini', '.cfg'})
    if not config_files:
        findings.append(_missing('DESIGN-CONFIG-001', 'experiments/configs'))
    plan = _text(root / 'experiments' / 'EXPERIMENT_PLAN.md')
    if not plan:
        findings.append(_missing('DESIGN-PLAN-001', 'experiments/EXPERIMENT_PLAN.md'))
    elif not re.search('(?:leak|group.?split|subject.?split|数据泄漏|分组划分)', plan, re.IGNORECASE):
        findings.append(_finding('DESIGN-LEAK-001', 'warning', 'validity', 'Experiment plan does not expose an independence/leakage control.', '实验计划没有明确分析单位、分组划分或泄漏控制，测试结果可能被相邻样本污染。', ['experiments/EXPERIMENT_PLAN.md'], 'Prespecify split ownership and preprocessing fit scope.'))
    if plan:
        design_dimensions = (('DESIGN-BASE-001', '(?:baseline|control|comparator|基线|对照)', '强基线或匹配对照'), ('DESIGN-ABL-001', '(?:ablation|component\\s+test|消融|组件实验)', '机制消融'), ('DESIGN-STAT-001', '(?:confidence\\s+interval|effect\\s+size|bootstrap|permutation|statistical|置信区间|效应量|统计检验)', '不确定性与统计分析'), ('DESIGN-FAIL-001', '(?:falsif|failure(?:\\s+(?:condition|criteria|interpretation))?|pivot|anti-claim|negative\\s+result|rejection\\s+rule|证伪|失败条件|失败标准|转向条件|反声明|拒绝条件)', '证伪或失败条件'))
        for check_id, pattern, label in design_dimensions:
            if not re.search(pattern, plan, re.IGNORECASE):
                findings.append(_finding(check_id, 'warning', 'experimental_validity', f'Experiment plan does not expose {label}.', f'实验计划没有明确{label}，即使代码可运行也可能无法区分机制贡献与替代解释。', ['experiments/EXPERIMENT_PLAN.md', 'experiments/METHOD_CONTRACT.json'], f'Add an executable, prespecified {label} block tied to a frozen claim.'))
        placeholder = _placeholder_excerpt(plan)
        if placeholder:
            findings.append(_finding('DESIGN-TEMPLATE-001', 'blocker', 'artifact_quality', f'Experiment plan still contains template text: {placeholder}', '实验计划仍有模板占位内容，运行契约可能只是脚手架而不是可执行方案。', ['experiments/EXPERIMENT_PLAN.md'], 'Resolve every placeholder that affects data, method, comparison, metric, or stopping criteria.'))
    # The exp-run producer validates its result manifest after design acceptance.
    # Requiring it here routes design repair downstream and creates a dependency cycle.
    return {key: value for key, value in locals().items() if key in ['check_id', 'config_files', 'design_dimensions', 'exc', 'label', 'path', 'pattern', 'placeholder', 'plan', 'source_files']}

def audit(service: Any, root: Path, options: dict[str, Any]) -> list[dict[str, Any]]:
    state = {'root': root, 'service': service, 'options': options}
    try:
        state.update(_rule_1(options=state['options'], root=state['root']))
        state.update(_rule_2(command_files=state['command_files'], error=state['error'], findings=state['findings'], options=state['options'], root=state['root'], run_spec=state['run_spec']))
        state.update(_rule_3(findings=state['findings'], root=state['root']))
    except _EarlyReturn as returned:
        return returned.value
    return state.get('findings', [])
