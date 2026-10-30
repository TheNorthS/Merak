"""Split execution workflow responsibilities."""

# ruff: noqa: F403, F405
from .engine_context import *

class ExecutionMixin:
    async def _ensure_patent_prior_art(self, run: WorkflowRun, research_direction: str, opts: dict) -> Path:
        """Execute configured patent retrieval and persist an auditable artifact."""
        from dataclasses import asdict
        from datetime import datetime
        from ..services.patent_tools import patent_tools
        root = Path(run.project_path).resolve()
        ideas_path = root / 'ideas' / 'ideas.md'
        idea_excerpt = ''
        if ideas_path.is_file():
            idea_excerpt = ideas_path.read_text(encoding='utf-8', errors='replace')[:2500]
        query_parts = [research_direction.strip()]
        for line in idea_excerpt.splitlines():
            clean = line.strip().strip('#*-| ')
            if len(clean) >= 20 and (not clean.lower().startswith(('rank', 'idea |', '---'))):
                query_parts.append(clean[:240])
                if len(query_parts) >= 4:
                    break
        query = ' '.join((part for part in query_parts if part))[:1000]
        if not query:
            raise RuntimeError('Patent search was enabled but no research/idea query could be constructed')
        current_year = datetime.now().year
        year_from = int(opts.get('patent_date_from') or 2000)
        year_to = int(opts.get('patent_date_to') or current_year)
        max_results = max(1, min(50, int(opts.get('patent_max_results') or 15)))
        results = await patent_tools.search_patents(query, max_results=max_results, date_from=f'{year_from}-01-01', date_to=f'{year_to}-12-31')
        if results:
            analysis = await patent_tools.analyze_prior_art(query, [], search_results=results)
            overlap_summary = analysis.overlap_summary
            novelty_assessment = analysis.novelty_assessment
            differentiation = analysis.suggested_differentiation
        else:
            overlap_summary = 'No records were returned by the configured provider.'
            novelty_assessment = 'INCONCLUSIVE: zero returned records is not evidence of patent novelty; query coverage, jurisdictions, classifications, and family records still require review.'
            differentiation = []
        payload = {'schema_version': 1, 'query': query, 'date_from': year_from, 'date_to': year_to, 'max_results': max_results, 'provider_config_verified': True, 'search_status': 'completed' if results else 'completed_no_records', 'records_returned': len(results), 'patents': [asdict(item) for item in results], 'overlap_summary': overlap_summary, 'novelty_assessment': novelty_assessment, 'suggested_differentiation': differentiation, 'limitations': ['This is a machine-assisted prior-art screen, not a legal patentability opinion.', 'A zero-result query must not be converted into a novelty claim.', 'Claims, patent families, CPC/IPC classes, jurisdictions, and non-patent literature require follow-up.'], 'created_at': time.time()}
        output = root / 'ideas' / 'patent_prior_art.json'
        output.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(output, payload)
        markdown = ['# Patent Prior-Art Screen', '', f'- Query: {query}', f'- Filing/publication window: {year_from}-{year_to}', f'- Records returned: {len(results)} / {max_results}', '', '## Assessment', novelty_assessment, '', '## Candidate Records']
        if results:
            markdown.extend((f"- [{item.patent_id or 'unknown'}] {item.title or '(title unavailable)'} | {item.applicant or 'unknown applicant'} | {item.url}" for item in results))
        else:
            markdown.append('- No records returned; coverage remains inconclusive.')
        markdown.extend(['', '## Limitations'])
        markdown.extend((f'- {item}' for item in payload['limitations']))
        atomic_write_text(root / 'ideas' / 'patent_prior_art.md', '\n'.join(markdown) + '\n')
        await self._emit(run, 'patent_search_completed', {'node_id': 'novelty', 'artifact': str(output), 'records': len(results), 'date_from': year_from, 'date_to': year_to})
        return output

    async def _ensure_knowledge_source_context(self, run: WorkflowRun, research_direction: str, opts: dict) -> list[Path]:
        """Materialize enabled personal-library sources before model synthesis."""
        strategy = dict(opts.get('research_strategy') or {})
        sources = {str(item) for item in strategy.get('literature_sources', [])}
        use_zotero = bool(opts.get('enable_zotero') and 'zotero' in sources)
        use_obsidian = bool(opts.get('enable_obsidian') and 'obsidian' in sources)
        if not use_zotero and (not use_obsidian):
            return []
        from ..services.knowledge_sources import knowledge_source_service
        results = await knowledge_source_service.collect_for_project(run.project_path, research_direction, zotero=use_zotero, obsidian=use_obsidian, limit=max(5, min(40, int(strategy.get('literature_max_papers') or 35))))
        paths = [Path(item.artifact_path) for item in results]
        run.options['_precollected_literature_sources'] = [item.source for item in results if item.status in {'completed', 'completed_no_records'}]
        await self._emit(run, 'knowledge_sources_collected', {'node_id': 'lit', 'sources': [item.source for item in results], 'artifacts': [item.artifact_path for item in results], 'records': {item.source: len(item.records) for item in results}})
        return paths

    async def _prepare_overleaf_compile(self, run: WorkflowRun, opts: dict) -> None:
        """Merge the latest Overleaf revision before compiling the paper."""
        from ..services.overleaf_sync import overleaf_sync
        project_id = str(opts.get('overleaf_project_id') or '').strip()
        await self._emit(run, 'overleaf_sync_started', {'node_id': 'compile', 'project_id': project_id, 'phase': 'pull'})
        from ..services.overleaf_research_revision import workflow_sync
        with workflow_sync(run.id):
            result = await overleaf_sync.prepare_sync(project_id, f'MERAK workflow {run.id}: prepare compile')
        await self._emit(run, 'overleaf_sync_result', {'node_id': 'compile', 'project_id': project_id, 'phase': 'pull', 'success': result.success, 'message': result.message, 'conflicts': result.conflicts, 'files_changed': result.files_changed})
        if not result.success:
            detail = ', '.join(result.conflicts) if result.conflicts else result.message
            raise RuntimeError(f'Overleaf pre-compile sync failed: {detail}')
        project = overleaf_sync._projects.get(project_id)
        if project and project.last_imported_files:
            from ..contracts.preparation import PreparationContractError
            changed = tuple(project.last_imported_files)
            owner = "figure" if any(path.startswith("figures/") for path in changed) else "paper"
            raise PreparationContractError(
                "Overleaf imported publication changes; revalidate the changed source and its "
                "dependent reviews before compiling or pushing.", owner=owner, paths=changed)

    async def _finish_overleaf_compile(self, run: WorkflowRun, opts: dict) -> None:
        """Push only after the compile artifact has passed its acceptance gate."""
        from ..services.overleaf_sync import overleaf_sync
        project_id = str(opts.get('overleaf_project_id') or '').strip()
        from ..services.overleaf_research_revision import workflow_sync
        with workflow_sync(run.id):
            result = await overleaf_sync.push(project_id, f'MERAK workflow {run.id}: verified paper compile')
        await self._emit(run, 'overleaf_sync_result', {'node_id': 'compile', 'project_id': project_id, 'phase': 'push', 'success': result.success, 'message': result.message, 'conflicts': result.conflicts, 'files_changed': result.files_changed})
        if not result.success:
            raise RuntimeError(f'Overleaf post-compile push failed: {result.message}')

    async def _observe_meta_optimization(self, run: WorkflowRun, failed_nodes: list[WorkflowNode]) -> None:
        """Record repeated failures and emit approval-only skill mutations."""
        from ..services.meta_optimize import get_meta_optimize_gate
        gate = get_meta_optimize_gate(run.project_path)
        for node in failed_nodes:
            raw_error = ' '.join(str(node.error or 'acceptance gate failed').split())
            signature = raw_error.lower()
            signature = re.sub('[a-z]:[/\\\\][^\\s]+|/(?:[^\\s/]+/)+[^\\s]+', '<path>', signature)
            signature = re.sub('\\b[0-9a-f]{8,}\\b', '<id>', signature)
            signature = re.sub('\\b\\d+(?:\\.\\d+)?\\b', '<n>', signature)[:500]
            result = gate.observe_workflow_failure(skill_name=node.skill.lstrip('/'), signature=signature, run_id=run.id, details=raw_error)
            await self._emit(run, 'meta_optimization_observed', {'node_id': node.id, 'skill': node.skill.lstrip('/'), 'observations': result.get('observations', 0), 'proposed': result.get('proposed', False), 'mutation_id': result.get('mutation_id', ''), 'reason': result.get('reason', '')})

    @staticmethod
    def _meta_optimization_candidates(run: WorkflowRun, durable_state: dict[str, Any]) -> list[WorkflowNode]:
        """Include quality-gate pauses as observations, not only hard crashes."""
        candidates = [node for node in run.nodes if node.status == NodeStatus.FAILED]
        seen = {node.id for node in candidates}
        phases = durable_state.get('phases') if isinstance(durable_state, dict) else {}
        phases = phases if isinstance(phases, dict) else {}
        for node in run.nodes:
            if node.id in seen:
                continue
            phase = phases.get(node.id) if isinstance(phases.get(node.id), dict) else {}
            if phase.get('status') != 'awaiting_revision':
                continue
            details = phase.get('details') if isinstance(phase.get('details'), dict) else {}
            revision = details.get('revision') if isinstance(details.get('revision'), dict) else {}
            last_gate = revision.get('last_gate') if isinstance(revision.get('last_gate'), dict) else {}
            issues = last_gate.get('issues') if isinstance(last_gate.get('issues'), list) else []
            summary = str(last_gate.get('summary') or last_gate.get('reason') or 'quality gate paused')
            evidence = '; '.join((str(item) for item in issues[:8]))
            candidates.append(WorkflowNode(id=node.id, name=node.name, skill=node.skill, error=(summary + (f'; {evidence}' if evidence else ''))[:4000]))
        return candidates

    @staticmethod
    def _skill_invocation_traces(project_path: str, skill_name: str, started_at: float) -> list[dict[str, Any]]:
        trace_root = Path(project_path).expanduser().resolve() / '.merak' / 'skill-invocations'
        traces: list[dict[str, Any]] = []
        if not trace_root.is_dir():
            return traces
        for path in trace_root.glob(f"*_{skill_name.lstrip('/')}.json"):
            try:
                payload = json.loads(path.read_text(encoding='utf-8'))
            except (OSError, json.JSONDecodeError):
                continue
            if float(payload.get('started_at') or 0) < started_at - 1:
                continue
            traces.append({**payload, 'trace_path': str(path)})
        return sorted(traces, key=lambda item: float(item.get('started_at') or 0))

    async def _runtime_execution_started(self, node: WorkflowNode, run: WorkflowRun, opts: dict[str, Any], runtime_service: str='') -> tuple[str, str]:
        """Record and announce runtime ownership without claiming a model skill ran."""
        from ..services.skill_orchestrator import skill_orchestrator
        plan = skill_orchestrator.select(node.id, node.skill, run.project_path, dict(opts or {}))
        service = str(runtime_service or plan.runtime_service or 'workflow_runtime')
        if node.id == 'results' and (plan.execution_contract_issues or service != plan.runtime_service):
            raise ValueError('Results runtime service does not match the current execution contract; no execution record was written.')
        trace_path = skill_orchestrator.record(run.project_path, run.id, plan)
        operation_id = uuid.uuid4().hex[:12]
        skill_orchestrator.mark_runtime_execution(run.project_path, run.id, node.id, service, 'running', operation_id=operation_id)
        await self._emit(run, 'skill_plan_selected', {'node_id': node.id, 'primary': plan.primary, 'specialists': plan.specialists, 'validators': plan.validators, 'registry_total': plan.registry_total, 'trace_path': str(trace_path), 'execution_kind': plan.execution_kind, 'runtime_service': service, 'policy_required': plan.policy_required})
        await self._emit(run, 'runtime_execution_started', {'node_id': node.id, 'runtime_service': service, 'operation_id': operation_id})
        return (operation_id, service)

    async def _runtime_execution_finished(self, node: WorkflowNode, run: WorkflowRun, operation_id: str, runtime_service: str, *, output: str='', error: str='') -> None:
        from ..services.skill_orchestrator import skill_orchestrator
        status = 'failed' if error else 'completed'
        skill_orchestrator.mark_runtime_execution(run.project_path, run.id, node.id, runtime_service, status, operation_id=operation_id, output=output, error=error)
        await self._emit(run, f'runtime_execution_{status}', {'node_id': node.id, 'runtime_service': runtime_service, 'operation_id': operation_id, 'error': error[:500]})

    def _managed_experiment_acceptance_gate(self, run: WorkflowRun, options: dict[str, Any]) -> dict[str, Any]:
        """Revalidate workflow-owned run manifests during durable resume."""
        from ..services.experiment_runner import JobStatus, experiment_scheduler
        root = Path(run.project_path).resolve()
        run_spec_path = root / 'experiments' / 'RUN_SPEC.json'
        if not run_spec_path.is_file():
            return {'accepted': False, 'reason': 'managed experiment run contract is missing', 'summary': f'Missing {run_spec_path}', 'details': {'issues': [f'missing run contract: {run_spec_path}'], 'run_spec_path': str(run_spec_path)}}
        try:
            run_spec = json.loads(run_spec_path.read_text(encoding='utf-8-sig', errors='strict'))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            issue = f'invalid experiments/RUN_SPEC.json: {type(exc).__name__}: {exc}'
            return {'accepted': False, 'reason': 'managed experiment run contract is invalid', 'summary': issue, 'details': {'issues': [issue], 'run_spec_path': str(run_spec_path)}}
        if not isinstance(run_spec, dict):
            issue = 'experiments/RUN_SPEC.json must contain a JSON object'
            return {'accepted': False, 'reason': 'managed experiment run contract is invalid', 'summary': issue, 'details': {'issues': [issue], 'run_spec_path': str(run_spec_path)}}
        from ..services.experiment_output_failure import source_bound_experiment_id
        experiment_id = source_bound_experiment_id(root, run.id)
        experiment = experiment_scheduler.get_experiment(experiment_id)
        manifest_refs: list[Any] = []
        manifest_paths: list[str] = []
        issues: list[str] = []
        if experiment is not None:
            if Path(experiment.project_path).resolve() != root:
                issues.append('workflow experiment scheduler entry belongs to a different project')
            if not experiment.jobs:
                issues.append('workflow experiment has no managed jobs')
            for job in experiment.jobs:
                manifest_refs.append(job)
                manifest_paths.append(str(job.manifest_path or ''))
                if job.status != JobStatus.COMPLETED:
                    issues.append(f'managed experiment job {job.id} is {job.status.value}, not completed')
        else:
            runtime_root = root / '.merak' / 'experiments'
            job_prefix = experiment_id[:56]
            persisted = sorted(runtime_root.glob(f'{job_prefix}-seed-*/run.json') if runtime_root.is_dir() else [])
            manifest_refs.extend(persisted)
            manifest_paths.extend((str(path) for path in persisted))
        if not manifest_refs:
            issues.append(f'no workflow-managed run manifest was found for {experiment_id}')
        from ..services.execution_cell_binding import persisted_matrix_issues
        try:
            issues.extend(persisted_matrix_issues(run_spec, experiment_id, manifest_refs))
        except ValueError as error:
            issues.append(str(error))
        for manifest_ref in manifest_refs:
            issues.extend(self._managed_experiment_output_issues(root, run_spec, manifest_ref))
        if not issues:
            from ..services.experiment_aggregation_validation import aggregation_issues
            from ..contracts.preparation import PreparationContractError
            try:
                issues.extend(aggregation_issues(root, run_spec, experiment_id))
            except PreparationContractError as error:
                return {'accepted': False, 'reason': 'aggregation producer contract failed', 'summary': str(error), 'details': error.details()}
        issues = list(dict.fromkeys((str(item) for item in issues if str(item).strip())))
        details = {'issues': issues, 'experiment_id': experiment_id, 'run_spec_path': str(run_spec_path), 'manifest_paths': manifest_paths, 'jobs_checked': len(manifest_refs)}
        if issues:
            return {'accepted': False, 'reason': 'managed experiment evidence contract failed', 'summary': '; '.join(issues[:8]), 'details': details}
        return {'accepted': True, 'verdict_id': self._verdict_id('managed-experiment-output-contract', [run_spec_path, *[Path(path) for path in manifest_paths if path]]), 'reviewer': 'deterministic:managed-experiment-output-contract', 'summary': 'Every RUN_SPEC per-run output is non-empty, parseable, owned by the completed attempt, and bound by provenance.json.', 'details': details}

    @staticmethod
    def _replace_local_python_launcher(command: str, executable: str) -> str:
        """Bind a generic Python command to this interpreter on local runs."""
        import subprocess
        if not re.match('^python(?:3(?:\\.\\d+)?)?\\s+', command):
            return command
        replacement = subprocess.list2cmdline([executable])
        return re.sub('^python(?:3(?:\\.\\d+)?)?', lambda _match: replacement, command, count=1)

    async def _execute_bounded_paper_table_repair(self, *, node: WorkflowNode, run: WorkflowRun, diagnostics: dict[str, Any], target_files: list[str], user_feedback: str='') -> str:
        """Edit only explicitly named manuscript table sources."""
        from ..agent.tools import invoke_skill
        from ..services.paper_drafting import paper_drafting_service
        from ..services.skill_orchestrator import skill_orchestrator
        root = Path(run.project_path).expanduser().resolve()
        paper_root = (root / 'paper').resolve()
        normalized_targets: list[str] = []
        resolved_targets: list[Path] = []
        for raw_target in target_files:
            relative = str(raw_target or '').strip().replace('\\', '/')
            candidate = (root / relative).resolve()
            if not relative.casefold().startswith('paper/tables/') or candidate.suffix.casefold() != '.tex' or (not candidate.is_relative_to(paper_root)):
                raise RuntimeError('Unsupported bounded paper artifact target: ' + relative)
            normalized = candidate.relative_to(root).as_posix()
            if normalized not in normalized_targets:
                normalized_targets.append(normalized)
                resolved_targets.append(candidate)
        if not resolved_targets:
            raise RuntimeError('Paper table repair was selected without a canonical .tex target.')
        before = {relative: artifact_state(path) for relative, path in zip(normalized_targets, resolved_targets)}
        manifest_path = root / 'paper' / 'tables' / 'TABLE_MANIFEST.json'
        try:
            manifest_before = json.loads(manifest_path.read_text(encoding='utf-8-sig'))
        except (OSError, UnicodeError, json.JSONDecodeError):
            manifest_before = None
        findings = [dict(item) for item in diagnostics.get('findings', []) if isinstance(item, dict)]
        target_set = set(normalized_targets)
        relevant_messages = list(dict.fromkeys((str(finding.get('message') or finding.get('plain_message') or '').strip() for finding in findings if target_set.intersection({str(value).replace('\\', '/') for value in finding.get('target_files', []) if str(value).strip()}) and str(finding.get('message') or finding.get('plain_message') or '').strip())))
        if not relevant_messages:
            relevant_messages = [str(item).strip() for item in diagnostics.get('issues', []) if str(item).strip()]
        issue_text = '\n'.join((f'- {item}' for item in relevant_messages)) or '- Repair the reported table layout defect.'
        target_text = '\n'.join((f'- {path}' for path in resolved_targets))
        feedback_text = '\nResearcher feedback:\n' + user_feedback.strip() if user_feedback.strip() else ''
        plan = skill_orchestrator.select(node.id, node.skill, run.project_path, {**dict(run.options or {}), 'bounded_paper_table_repair': True})
        await self._emit(run, 'paper_table_repair_started', {'node_id': node.id, 'skill': plan.primary, 'target_files': normalized_targets})
        result = await invoke_skill(plan.primary, f'Repair only the explicitly listed manuscript table sources.\n\nCanonical project root: {root}\nPermitted write targets:\n{target_text}\n\nIndependent findings:\n{issue_text}\n\nRead the current table source and the manuscript context needed to understand\nits columns and caption. Improve legibility and publication layout without\nchanging registered numbers, labels, evidence meaning, or scientific claims.\nDo not edit any section, main.tex, generated figure, manifest, review report,\nor workflow state. Re-read every changed target before returning.\n{feedback_text}\n', project_path=run.project_path, parent_context='skill-chain:workflow>paper-table-repair', allowed_tools_override=['Read', 'Write', 'Edit', 'Glob', 'Grep'], invocation_contract='The only permitted write targets are:\n' + target_text + '\nA response without an actual target-file edit is incomplete.', max_iterations=12)
        after = {relative: artifact_state(path) for relative, path in zip(normalized_targets, resolved_targets)}
        changed_targets = [relative for relative in normalized_targets if not artifact_state_equal(before[relative], after[relative])]
        await self._emit(run, 'paper_table_repair_completed', {'node_id': node.id, 'skill': plan.primary, 'target_files': normalized_targets, 'changed_target_files': changed_targets})
        if not changed_targets:
            raise RuntimeError('Bounded paper table repair returned without changing any permitted target artifact.')
        rebind = paper_drafting_service.rebind_layout_only_derived_inputs(run.project_path, dict(run.options or {}), before_manifest=manifest_before, target_files=normalized_targets)
        if not rebind.get('passed'):
            raise RuntimeError('Bounded paper table repair failed scientific rebind: ' + '; '.join((str(item) for item in rebind.get('issues') or [])))
        return result

    async def _execute_staged_paper(self, *, node: WorkflowNode, run: WorkflowRun, research_direction: str, opts: dict, revision_issues: Optional[list[str]]=None) -> str:
        """Load paper-write for independent, resumable section invocations."""
        from ..services.paper_preparation_errors import prepare_paper_evidence
        from ..services.paper_drafting import PAPER_STAGE_LABELS, PAPER_STAGE_ORDER, PaperDraftingError, paper_drafting_service
        from ..services.skill_orchestrator import skill_orchestrator
        self._ensure_agent_tools()
        from .paper_method_presentation import refresh_method_presentation
        await refresh_method_presentation(run)
        prepare_paper_evidence(run.project_path, research_direction)
        plan = skill_orchestrator.select(node.id, node.skill, run.project_path, {**opts, 'staged_paper': True})
        trace_path = skill_orchestrator.record(run.project_path, run.id, plan)
        await self._emit(run, 'skill_plan_selected', {'node_id': node.id, 'primary': plan.primary, 'specialists': plan.specialists, 'validators': plan.validators, 'registry_total': plan.registry_total, 'trace_path': str(trace_path), 'execution_kind': plan.execution_kind, 'runtime_service': plan.runtime_service, 'policy_required': plan.policy_required, 'execution_mode': 'section-by-section'})
        paper_skill_started_at = time.time()
        skill_orchestrator.mark_execution(run.project_path, run.id, node.id, plan.primary, 'running', role='primary', policy_loaded=True, execution_kind='hybrid')
        await self._emit(run, 'skill_dispatch_started', {'node_id': node.id, 'skill': plan.primary, 'role': 'primary', 'execution_mode': 'section-by-section'})
    
        async def emit_paper_event(event: str, payload: dict[str, Any]) -> None:
            await self._emit(run, event, {'node_id': node.id, **payload})
    
        async def invoke_stage(stage_id: str, prompt: str, contract: str) -> str:
    
            async def on_stage_event(event) -> None:
                from .model_progress_fields import model_progress_fields
                data = event.data if isinstance(event.data, dict) else {}
                if event.type == 'status':
                    await self._emit(run, 'paper_stage_agent_status', {'node_id': node.id, 'stage_id': stage_id, 'stage_label': PAPER_STAGE_LABELS.get(stage_id, stage_id), 'stage_index': PAPER_STAGE_ORDER.index(stage_id) + 1, 'stage_total': len(PAPER_STAGE_ORDER), 'status': str(data.get('status') or ''), 'provider': str(data.get('provider') or ''), 'model': str(data.get('model') or ''), **model_progress_fields(data)})
                elif event.type == 'tool_call':
                    await self._emit(run, 'agent_tool_call', {'node_id': node.id, 'paper_stage': stage_id, 'tool': str(data.get('name') or ''), 'args': str(data.get('args') or '')[:400]})
                elif event.type == 'tool_result':
                    await self._emit(run, 'agent_tool_result', {'node_id': node.id, 'paper_stage': stage_id, 'tool': str(data.get('name') or ''), 'success': bool(data.get('success', True)), 'output': str(data.get('output') or '')[:600]})
                elif event.type == 'step':
                    await self._emit(run, 'agent_step', {'node_id': node.id, 'paper_stage': stage_id, **data})
    
            async def invoke_once() -> str:
                from .paper_stage_invocation import invoke_paper_stage
                return await invoke_paper_stage(self, node, run, plan.primary, prompt, contract, on_stage_event, stage_id=stage_id)
    
            def recover_valid_stage_artifact() -> Optional[str]:
                paper_paths = paper_drafting_service.paths(run.project_path)
                outputs = paper_drafting_service.stage_outputs(paper_paths, stage_id)
                if not outputs or not all((path.is_file() and path.stat().st_size > 0 for path in outputs)):
                    return None
                review = paper_drafting_service.validate_stage(run.project_path, stage_id)
                if not review.get('passed'):
                    return None
                return 'Recovered a valid canonical paper-stage artifact after the model transport ended before its final response.'
            return await self._execute_with_model_transport_retry(run=run, node_id=node.id, operation_name=f'paper/{stage_id}', stage_id=stage_id, operation=invoke_once, opts=opts, recovery_probe=recover_valid_stage_artifact)
    
        def record_section_traces(*, terminal_status: str, output: str='', error: str='') -> tuple[list[dict[str, Any]], str, dict[str, Any]]:
            traces = self._skill_invocation_traces(run.project_path, plan.primary, paper_skill_started_at)
            for trace in traces:
                skill_orchestrator.mark_execution(run.project_path, run.id, node.id, plan.primary, 'completed' if trace.get('status') == 'completed' else 'failed', role='section', session_id=str(trace.get('session_id') or ''), error=str(trace.get('error') or ''), policy_loaded=True, execution_kind='model_owned', model_provider=str(trace.get('model_provider') or ''), model_name=str(trace.get('model_name') or ''))
            primary_trace = traces[0] if traces else {}
            primary_session_id = str(primary_trace.get('session_id') or '')
            skill_orchestrator.mark_execution(run.project_path, run.id, node.id, plan.primary, terminal_status, role='primary', session_id=primary_session_id, output=output, error=error, policy_loaded=bool(primary_session_id), execution_kind='hybrid', model_provider=str(primary_trace.get('model_provider') or ''), model_name=str(primary_trace.get('model_name') or ''))
            return (traces, primary_session_id, primary_trace)
        try:
            result = await paper_drafting_service.draft(run.project_path, research_direction, opts, invoke_stage, emit_paper_event, revision_issues=revision_issues)
        except PaperDraftingError as exc:
            traces, primary_session_id, _ = record_section_traces(terminal_status='revision_required', error=str(exc))
            stage_index = PAPER_STAGE_ORDER.index(exc.stage_id) + 1 if exc.stage_id in PAPER_STAGE_ORDER else 0
            await self._emit(run, 'skill_invocation_revision_required', {'node_id': node.id, 'skill': plan.primary, 'stage_id': exc.stage_id, 'stage_label': PAPER_STAGE_LABELS.get(exc.stage_id, exc.stage_id), 'stage_index': stage_index, 'stage_total': len(PAPER_STAGE_ORDER), 'issues': exc.issues[:12], 'model_invoked': bool(primary_session_id), 'model_session_ids': [str(trace.get('session_id') or '') for trace in traces if str(trace.get('session_id') or '')]})
            return json.dumps({'status': 'revision_required', 'failed_stage': exc.stage_id, 'issues': exc.issues, 'model_invoked': bool(primary_session_id), 'model_session_ids': [str(trace.get('session_id') or '') for trace in traces if str(trace.get('session_id') or '')], 'message': 'Section-by-section drafting stopped at the responsible stage; accepted sections and hashes were preserved.'}, ensure_ascii=False, indent=2)
        except Exception as exc:
            error = self._exception_summary(exc)
            transport_error = self._is_transport_research_error(exc)
            skill_orchestrator.mark_execution(run.project_path, run.id, node.id, plan.primary, 'interrupted' if transport_error else 'failed', role='primary', error=error, policy_loaded=True, execution_kind='hybrid')
            await self._emit(run, 'skill_invocation_interrupted' if transport_error else 'skill_invocation_failed', {'node_id': node.id, 'skill': plan.primary, 'role': 'primary', 'error': error, 'error_category': 'transport' if transport_error else 'node_execution', 'retryable': transport_error})
            raise
        summary = json.dumps(result, ensure_ascii=False, indent=2)
        _, primary_session_id, _ = record_section_traces(terminal_status='completed' if self._skill_invocation_traces(run.project_path, plan.primary, paper_skill_started_at) else 'reused', output=summary)
        await self._emit(run, 'skill_invocation_completed' if primary_session_id else 'skill_invocation_reused', {'node_id': node.id, 'skill': plan.primary, 'role': 'primary', 'execution_mode': 'section-by-section'})
        return summary

    @staticmethod
    def _agent_event_counts_as_progress(event: Any) -> bool:
        """Return whether an Agent event demonstrates semantic progress.
    
            Status pulses such as ``waiting_model`` and ``skill_delegate_running``
            are liveness only. Counting them as work lets a wedged provider or
            nested skill refresh the parent idle deadline forever.
            """
        return str(getattr(event, 'type', '')) in {'text', 'tool_call', 'tool_result', 'step', 'done', 'error'}

    async def _await_agent_with_activity_watchdog(self, *, task: asyncio.Task, run: WorkflowRun, node: WorkflowNode, is_revision: bool, last_activity: Callable[[], float]) -> Any:
        """Wait for an agent while distinguishing inactivity from useful work.
    
            Status heartbeats do not count as progress. The request layer owns
            its shorter deadline; this outer guard bounds a whole node session.
            """
        idle_limit = self._agent_node_timeout_seconds(node.id, is_revision=is_revision)
        hard_limit = self._agent_node_hard_timeout_seconds(node.id, is_revision=is_revision)
        started = time.monotonic()
        last_heartbeat = started
        poll_interval = 10.0
        try:
            while True:
                now = time.monotonic()
                elapsed = max(0.0, now - started)
                idle_for = max(0.0, now - float(last_activity()))
                hard_remaining = max(0.0, hard_limit - elapsed)
                idle_remaining = max(0.0, idle_limit - idle_for)
                if hard_remaining <= 0 or idle_remaining <= 0:
                    kind = 'hard' if hard_remaining <= 0 else 'idle'
                    limit = hard_limit if kind == 'hard' else idle_limit
                    from ..agent.tool_deadline import cancel_tool_task
                    await cancel_tool_task(task, 5.0)
                    raise AgentNodeWatchdogTimeout(node_id=node.id, kind=kind, limit_seconds=limit, elapsed_seconds=elapsed, idle_seconds=idle_for)
                done, _ = await asyncio.wait({task}, timeout=max(0.01, min(poll_interval, hard_remaining, idle_remaining)))
                if done:
                    return await task
                now = time.monotonic()
                if now - last_heartbeat >= 30.0:
                    last_heartbeat = now
                    await self._emit(run, 'node_agent_watchdog_heartbeat', {'node_id': node.id, 'elapsed_seconds': round(now - started, 1), 'idle_seconds': round(max(0.0, now - float(last_activity())), 1), 'idle_limit_seconds': idle_limit, 'hard_limit_seconds': hard_limit, 'is_revision': is_revision})
        except asyncio.CancelledError:
            from ..agent.tool_deadline import cancel_tool_task
            await cancel_tool_task(task, 5.0)
            raise

    @staticmethod
    def _agent_node_timeout_seconds(node_id: str, *, is_revision: bool) -> float:
        """Idle-time policy; active model/tool events reset this deadline.
    
            Request retries share 300 seconds. Keep the outer inactivity guard
            above that budget plus cancellation cleanup; status pulses do not
            extend it. Independent node hard ceilings still apply.
            """
        base_timeout = {'lit': 600.0, 'novelty': 600.0, 'idea': 300.0, 'exp-design': 300.0, 'results': 360.0, 'narrative': 360.0, 'figure': 720.0, 'paper': 360.0, 'ppt': 360.0}.get(node_id, 360.0)
        return max(360.0, base_timeout)

    @staticmethod
    def _agent_node_hard_timeout_seconds(node_id: str, *, is_revision: bool) -> float:
        """Absolute ceiling after which even an active child is cancelled."""
        base_timeout = {'lit': 2400.0, 'novelty': 2400.0, 'idea': 1800.0, 'exp-design': 1800.0, 'results': 1200.0, 'narrative': 1800.0, 'figure': 3600.0, 'paper': 2400.0, 'ppt': 1800.0}.get(node_id, 1800.0)
        return max(1800.0, base_timeout) if is_revision else base_timeout

    async def _execute_profile_specialists(self, *, node: WorkflowNode, run: WorkflowRun, direction: str, opts: dict[str, Any]) -> dict[str, Any]:
        """Execute required profile subnodes without turning transport failure into a hard stop."""
        from ..services.research_specialists import research_specialist_service
    
        async def emit(event_type: str, payload: dict[str, Any]) -> None:
            await self._emit(run, event_type, payload)
        try:
            entries = await research_specialist_service.execute_for_node(run.project_path, run.id, node.id, direction, opts, [item.id for item in run.nodes], emit=emit)
        except Exception as exc:
            await self._emit(run, 'specialist_stage_incomplete', {'node_id': node.id, 'error': self._exception_summary(exc), 'message': '领域专家子节点未完成；宏节点将进入质量修订循环，不会把缺失产物当作已通过。'})
            return {'accepted': False, 'error': self._exception_summary(exc)}
        return {'accepted': True, 'subnodes': entries}
