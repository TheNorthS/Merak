"""gates b workflow engine responsibilities."""

# ruff: noqa: F403, F405
from .engine_context import *

class GatesBMixin:
    def _audit_acceptance_gate(self, project_path: str, assurance: str, result: str, *, evidence_mode: str='executed', run_id: str='', delivery_goal: str='submission_candidate') -> dict:
        audit_path = Path(project_path) / 'audit-results' / 'AUDIT_RESULTS.json'
        audit_build_path = Path(project_path) / 'audit-results' / 'AUDIT_BUILD.json'
        proof_path = Path(project_path) / 'paper' / 'PROOF_AUDIT.json'
        artifacts = [audit_path, audit_build_path, proof_path]
        from .review_audit import validate_audit_bundle
        try:
            _, _, executor_model = model_router.get_provider_route(ModelRole.EXECUTOR)
        except Exception:
            executor_model = ''
        bundle = validate_audit_bundle(project_path, run_id=run_id, evidence_mode=evidence_mode, executor_model=executor_model, allow_non_model_layers=evidence_mode in {'design_only', 'synthetic_preview', 'execution_pending', 'planned'})
        bundle_issues = list(bundle.get('issues') or [])
        proof_attestation = bundle.get('proof')
        proof_attestation = proof_attestation if isinstance(proof_attestation, dict) else {}
        if bundle.get('valid') is not True:
            return {'accepted': False, 'reason': 'audit bundle provenance or freshness validation failed', 'summary': '; '.join(bundle_issues[:8]), 'details': {'issues': bundle_issues, 'proof': proof_attestation, 'path': str(audit_path), 'bundle': {'layers': bundle.get('layers') or [], 'audit_runtime_signature': bundle.get('audit_runtime_signature'), 'reviewer_route_sha256': bundle.get('reviewer_route_sha256')}}}
        scientific_verdicts = list(bundle.get('scientific_verdicts') or [])
        from .draft_delivery import DRAFT, draft_audit_gate
        if delivery_goal == DRAFT:
            return draft_audit_gate(self, bundle, artifacts)
        verdicts = list(bundle.get('verdicts') or [])
        blockers = {Verdict.FAIL.value, Verdict.BLOCKED.value, Verdict.ERROR.value}
        failing = [verdict for verdict in verdicts if verdict in blockers]
        if failing:
            return {'accepted': False, 'reason': f"audit gate blocked by verdicts: {', '.join(failing)}", 'summary': f"Audit verdicts: {', '.join(verdicts)}", 'details': {'verdicts': verdicts, 'path': str(audit_path), 'assurance': assurance, 'evidence_mode': evidence_mode, 'scientific_verdicts': scientific_verdicts, 'proof': proof_attestation}}
        warning_verdicts = [verdict for verdict in verdicts if verdict == Verdict.WARN.value]
        warnings = []
        if warning_verdicts:
            warnings.append({'kind': 'node_risk', 'warning_count': len(warning_verdicts), 'issues': ['Five-layer audit retained author-review warnings: ' + ', '.join(warning_verdicts)], 'report_path': str(audit_path)})
        return {'accepted': True, 'verdict_id': self._verdict_id('audit', artifacts), 'reviewer': 'deterministic:audit-results', 'summary': f"Audit gate passed under assurance={assurance}, evidence_mode={evidence_mode}: {', '.join(verdicts)}.", 'details': {'verdicts': verdicts, 'path': str(audit_path), 'assurance': assurance, 'evidence_mode': evidence_mode, 'advisory_verdicts': warning_verdicts, 'scientific_verdicts': scientific_verdicts, 'proof': proof_attestation}, 'warnings': warnings}

    def _append_manifest(self, project_path: str, run_id: str, node_id: str, verdict_id: str, status: str, summary: str) -> None:
        """Append a durable workflow trace row to MANIFEST.md."""
        from datetime import datetime
        manifest = Path(project_path) / 'MANIFEST.md'
        cleaned = ' '.join(str(summary or '').split())[:500]
        cleaned = cleaned.replace('|', '\\|')
        timestamp = datetime.now().isoformat(timespec='seconds')
        row = f'| {timestamp} | {run_id} | {node_id} | {status} | {verdict_id} | {cleaned} |\n'
        with path_lock(manifest):
            if manifest.exists():
                existing = manifest.read_text(encoding='utf-8-sig', errors='strict')
            else:
                existing = '# Artifact Manifest\n\n| Time | Run | Node | Status | Verdict | Summary |\n|---|---|---|---|---|---|\n'
            if status == 'accepted' and f'| {run_id} | {node_id} | {status} | {verdict_id} |' in existing:
                return
            atomic_write_text(manifest, existing + row)

    def _find_node(self, run: WorkflowRun, node_id: str) -> Optional[WorkflowNode]:
        """在运行实例中查找节点"""
        for n in run.nodes:
            if n.id == node_id:
                return n
        return None

    @classmethod
    def _parse_training_check_result(
        cls, result: str, *, assurance: str,
    ) -> dict[str, Any]:
        from .training_check_result import parse_training_check_result

        return parse_training_check_result(
            result, assurance=assurance, target_resolver=cls._revision_target_files,
        )

    @staticmethod
    def _persist_training_check(run: WorkflowRun, assessment: dict[str, Any], raw_result: str) -> str:
        """Persist the exact reviewer response and normalized gate payload."""
        report_path = Path(run.project_path) / '.merak' / 'quality' / 'training_check.json'
        report_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {**assessment, 'run_id': run.id, 'checked_at': time.time(), 'raw_result': str(raw_result or '')}
        atomic_write_json(report_path, payload)
        return str(report_path)

    async def _run_code_review(self, run: WorkflowRun, direction: str, effort: str, assurance: str) -> str:
        """Run static experiment preflight through the complete /training-check skill."""
        from ..agent.tools import invoke_skill
        from ..agent.skill_resume import workflow_scope
        from ..services.implementation_review_completion import parse_review_checkpoint
        from ..services.implementation_review_receipt import review_source_hash
        review_node_id = workflow_scope.get()[1] or "exp-run"
        from ..services.project_scaffold import get_convention_paths
        from ..services.skill_orchestrator import skill_orchestrator
        paths = get_convention_paths(run.project_path)
        src_dir = Path(paths['experiments_src'])
        config_dir = Path(run.project_path) / 'experiments' / 'configs'
        skill_plan = skill_orchestrator.select('exp-run', '/experiment-bridge', run.project_path, {**dict(run.options or {}), 'assurance': assurance, 'effort': effort})
        skill_orchestrator.record(run.project_path, run.id, skill_plan)
        started_at = time.time()
        skill_orchestrator.mark_execution(run.project_path, run.id, review_node_id, 'training-check', 'running', role='preflight', policy_loaded=True, execution_kind='model_owned')
        arguments = f"""Perform a read-only pre-execution training and implementation audit.\n\nResearch direction: {direction}\nExperiment source: {src_dir}\nExperiment configs: {config_dir}\nRun contract: {Path(run.project_path) / 'experiments' / 'RUN_SPEC.json'}\nMethod contract: {Path(run.project_path) / 'experiments' / 'METHOD_CONTRACT.json'}\n\nCheck implementation completeness, data/split leakage, objective and metric correctness,\nseed handling, checkpoint selection, result provenance, resource assumptions, and whether\nthe accepted method is actually implemented. This invocation is read-only; do not run\ntraining or edit files.\n\nReturn one JSON object and no Markdown wrapper:\n{{\n  "verdict": "PASS|WARN|FAIL",\n  "summary": "concise overall decision",\n  "findings": [\n    {{\n      "id": "stable finding id",\n      "severity": "blocker|warning",\n      "category": "implementation|leakage|statistics|provenance|resources",\n      "message": "specific defect",\n      "target_files": ["project-relative/path"],\n      "evidence": ["file:symbol or exact observation"],\n      "remediation": "concrete bounded repair"\n    }}\n  ]\n}}\n"""
        try:
            from ..services.training_review_policy import review_scope_instruction
            from ..services.implementation_review_completion import review_completion_instruction
            arguments += '\n' + review_scope_instruction() + '\n' + review_completion_instruction()
            result = await invoke_skill('training-check', arguments, project_path=run.project_path, parent_context=f'skill-chain:workflow>{review_node_id}-preflight', allowed_tools_override=['Read', 'Glob', 'Grep'], invocation_contract='Read-only workflow preflight. Do not run experiments, invoke nested skills, or modify project artifacts.', max_iterations=12, resume_input_fingerprint=review_source_hash(Path(run.project_path)))
        except Exception as exc:
            traces = self._skill_invocation_traces(run.project_path, 'training-check', started_at)
            trace = traces[-1] if traces else {}
            skill_orchestrator.mark_execution(run.project_path, run.id, review_node_id, 'training-check', 'failed', role='preflight', session_id=str(trace.get('session_id') or ''), error=self._exception_summary(exc), policy_loaded=True, execution_kind='model_owned')
            raise
        traces = self._skill_invocation_traces(run.project_path, 'training-check', started_at)
        trace = traces[-1] if traces else {}
        skill_orchestrator.mark_execution(run.project_path, run.id, review_node_id, 'training-check', 'completed', role='preflight', session_id=str(trace.get('session_id') or ''), output=result, policy_loaded=True, execution_kind='model_owned')
        stop_reason = str(trace.get("stop_reason") or "")
        try:
            parse_review_checkpoint(self._parse_training_check_result, result, assurance=assurance,
                                    project_path=run.project_path, trace=trace)
            if stop_reason != "length":
                return result
        except ValueError as first_error:
            first_reason = str(first_error)
        else:
            first_reason = "finish_reason=length"
        from .training_check_result import (
            compact_training_check_instruction,
            protocol_failure_result,
        )
        try:
            from ..services.implementation_review_completion import format_repair_context
            compact_result = await invoke_skill(
                'training-check',
                arguments + "\n\n" + compact_training_check_instruction() + format_repair_context(result),
                project_path=run.project_path,
                parent_context='skill-chain:workflow>exp-run-preflight>training-check-retry',
                allowed_tools_override=[],
                invocation_contract='Read-only retry. Return only the compact JSON object; do not run experiments or edit files.',
                max_iterations=6,
            )
        except Exception as retry_error:
            return protocol_failure_result(
                f"initial={first_reason}; retry invocation={retry_error}",
                stop_reason,
            )
        retry_traces = self._skill_invocation_traces(
            run.project_path, 'training-check', started_at,
        )
        retry_trace = retry_traces[-1] if retry_traces else {}
        retry_stop_reason = str(retry_trace.get("stop_reason") or "")
        skill_orchestrator.mark_execution(
            run.project_path, run.id, review_node_id, 'training-check', 'completed',
            role='preflight-retry', session_id=str(retry_trace.get('session_id') or ''),
            output=compact_result, policy_loaded=True, execution_kind='model_owned',
        )
        try:
            parse_review_checkpoint(self._parse_training_check_result, compact_result, assurance=assurance,
                                    project_path=run.project_path, trace=trace)
            return compact_result
        except ValueError as retry_error:
            return protocol_failure_result(
                f"initial={first_reason}; retry={retry_error}",
                retry_stop_reason or stop_reason,
            )
