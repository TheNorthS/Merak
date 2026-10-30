"""Split execution workflow responsibilities."""

# ruff: noqa: F403, F405
from .engine_context import *
from ..utils.runtime_source_root import implementation_source_path

class ExecutionExtraMixin:
    async def _execute_stage_delegates(self, *, node: WorkflowNode, run: WorkflowRun, direction: str, effort: str, assurance: str, opts: dict) -> None:
        """Run required sub-skills as isolated sessions, never prompt excerpts."""
        if node.id != 'narrative':
            return
        from ..agent.tools import invoke_skill
        from ..services.paper_plan import paper_plan_service
        from ..services.paper_plan_asset_links import plan_asset_instruction, plan_link_issues
        from ..services.paper_plan_runtime import reuse_current_plan
        from ..services.skill_orchestrator import skill_orchestrator
        root = Path(run.project_path).expanduser().resolve()
        plan_path = paper_plan_service.path(root)
    
        def valid_plan() -> bool:
            return paper_plan_service.is_valid(plan_path) and not plan_link_issues(root)
        if not opts.get('_paper_plan_revision_instruction') and await reuse_current_plan(self, node, run, paper_plan_service):
            return
        target_venue = str(opts.get('target_venue') or 'ICLR')
        try:
            target_pages = int(opts.get('target_pages') or 0)
        except (TypeError, ValueError):
            target_pages = 0
        evidence_mode = str(opts.get('non_experiment_evidence_mode') or 'design_only').strip().casefold()
        canonical_candidates = [root / 'NARRATIVE_REPORT.md', root / 'ideas' / 'SELECTED_IDEA.json', root / 'literature' / 'references.bib', root / 'experiments' / 'EXPERIMENT_PLAN.md', root / 'experiments' / 'METHOD_CONTRACT.json', root / 'experiments' / 'RUN_SPEC.json', root / 'experiments' / 'results' / 'analysis.md', root / 'figures' / 'SCIENTIFIC_ASSET_PLAN.json', root / 'figures' / 'FIGURE_MANIFEST.json']
        result_input_dir = root / 'experiments' / 'results' / ('simulated' if evidence_mode == 'synthetic_preview' else 'templates')
        if result_input_dir.is_dir():
            canonical_candidates.extend((path for path in sorted(result_input_dir.iterdir()) if path.is_file()))
        existing_inputs = [path.relative_to(root).as_posix() for path in canonical_candidates if path.is_file()]
        input_inventory = '\n'.join((f'- {path}' for path in existing_inputs))
        evidence_contract = "Hash-bound generated tables establish record identity and descriptive scenario observations only. If the generator does not execute models, keep actual transfer, mechanism and preservation claims pending; never force scientific support or falsification from generated-label ordering. Preserve negative descriptive observations and explicit evidence gaps." if evidence_mode == 'synthetic_preview' else 'Use only verified executed or imported evidence; otherwise keep empirical maturity pending.'
        arguments = f"Build the paper plan from the accepted project artifacts.\n\nCanonical output (required): {plan_path}\nDo not write PAPER_PLAN.md at the project root.\nResearch direction: {direction}\nTarget venue: {target_venue}\nPreferred pages: {target_pages or 'venue default'} (soft target)\nEffort: {effort}\nAssurance: {assurance}\nEvidence contract: {evidence_contract}\n\nAuthoritative existing input inventory:\n{input_inventory or '- No canonical input artifacts are currently present.'}\n\nRead only paths in this inventory unless Glob first proves that another optional\nartifact exists. Do not probe guessed aliases or issue Read calls for absent\nfiles. A missing expected input is an evidence gap, not a path to guess.\nProduce a claims-evidence matrix, paper type, one-sentence contribution,\nsection-by-section purpose and page budget, figure/table placement, citation\nneeds, and explicit evidence gaps. This is a domain manuscript plan, not an\nMERAK execution report."
        from ..services.paper_plan_evidence import record_delegate_failure
        from ..services.paper_plan_delivery import plan_delivery
        delivery, delegate_tools = plan_delivery(root, paper_plan_service.is_valid(plan_path))
        arguments += plan_asset_instruction(root) + '\n' + str(opts.get('_paper_plan_revision_instruction') or '')
        arguments += delivery
        from ..services.research_delivery_prompt import research_delivery_instruction
        arguments += research_delivery_instruction(opts)
        source_hash = paper_plan_service._source_hash(root, paper_plan_service._source_paths(root))
        delegate_started_at = time.time()
        skill_orchestrator.mark_execution(run.project_path, run.id, node.id, 'paper-plan', 'running', role='delegate', policy_loaded=True, execution_kind='model_owned')
        await self._emit(run, 'skill_invocation_started', {'node_id': node.id, 'skill': 'paper-plan', 'role': 'delegate'})
        last_activity = time.monotonic()
    
        async def on_delegate_event(event) -> None:
            nonlocal last_activity
            from .model_progress_fields import model_progress_fields
            if self._agent_event_counts_as_progress(event):
                last_activity = time.monotonic()
            if event.type == 'status':
                data = event.data if isinstance(event.data, dict) else {}
                await self._emit(run, 'skill_invocation_progress', {'node_id': node.id, 'skill': 'paper-plan', 'status': str(data.get('status') or 'running'), 'elapsed': int(data.get('elapsed') or 0), 'model': str(data.get('model') or ''), **model_progress_fields(data)})
            elif event.type == 'tool_call':
                data = event.data if isinstance(event.data, dict) else {}
                await self._emit(run, 'agent_tool_call', {'node_id': node.id, 'skill': 'paper-plan', 'tool': str(data.get('name') or ''), 'args': str(data.get('args') or '')[:400]})
            elif event.type == 'tool_result':
                data = event.data if isinstance(event.data, dict) else {}
                await self._emit(run, 'agent_tool_result', {'node_id': node.id, 'skill': 'paper-plan', 'tool': str(data.get('name') or ''), 'success': bool(data.get('success', False)), 'output': str(data.get('output') or '')[:600]})
        try:
            delegate_task = asyncio.create_task(invoke_skill('paper-plan', arguments, project_path=run.project_path, parent_context='skill-chain:research-refine', workflow_node_id=node.id, on_event=on_delegate_event, allowed_tools_override=delegate_tools))
            delegate_result = await self._await_agent_with_activity_watchdog(
                task=delegate_task, run=run, node=node, is_revision=False, last_activity=lambda: last_activity,
            )
            if not valid_plan():
                raise RuntimeError('paper-plan completed without a valid canonical artifact: ' + str(plan_path) + '; ' + '; '.join(plan_link_issues(root)))
            paper_plan_service.record_existing(root, generator='model-authored:paper-plan-skill', expected_source_hash=source_hash)
        except Exception as exc:
            record_delegate_failure(root, run.id, source_hash, str(exc))
            skill_orchestrator.mark_execution(run.project_path, run.id, node.id, 'paper-plan', 'failed', role='delegate', session_id=str(self._skill_invocation_traces(run.project_path, 'paper-plan', delegate_started_at)[-1].get('session_id') or '') if self._skill_invocation_traces(run.project_path, 'paper-plan', delegate_started_at) else '', error=str(exc), policy_loaded=True, execution_kind='model_owned')
            await self._emit(run, 'skill_invocation_failed', {'node_id': node.id, 'skill': 'paper-plan', 'role': 'delegate', 'error': str(exc)[:500], 'manual_resume_required': True})
            raise
        skill_orchestrator.mark_execution(run.project_path, run.id, node.id, 'paper-plan', 'completed', role='delegate', session_id=str(self._skill_invocation_traces(run.project_path, 'paper-plan', delegate_started_at)[-1].get('session_id') or '') if self._skill_invocation_traces(run.project_path, 'paper-plan', delegate_started_at) else '', output=delegate_result, policy_loaded=True, execution_kind='model_owned')
        await self._emit(run, 'skill_invocation_completed', {'node_id': node.id, 'skill': 'paper-plan', 'role': 'delegate', 'artifact': str(plan_path)})

    @staticmethod
    def _selected_literature_sources(opts: Optional[dict]) -> tuple[str, ...]:
        strategy = dict((opts or {}).get('research_strategy') or {})
        raw_sources = strategy.get('literature_sources') or ('arxiv', 'semantic_scholar')
        if isinstance(raw_sources, str):
            raw_sources = [item.strip() for item in raw_sources.split(',') if item.strip()]
        return tuple(dict.fromkeys((str(item) for item in raw_sources if str(item) in LITERATURE_SOURCE_TOOLS)))

    def _literature_source_tool_contract(self, node_id: str, opts: Optional[dict]) -> dict[str, str]:
        if node_id not in LITERATURE_SEARCH_NODES:
            return {}
        return {source: LITERATURE_SOURCE_TOOLS[source] for source in self._selected_literature_sources(opts)}

    def _filter_literature_source_tools(self, node_id: str, opts: Optional[dict], enabled_tools: list[str]) -> list[str]:
        if node_id not in LITERATURE_SEARCH_NODES:
            return enabled_tools
        selected = self._literature_source_tool_contract(node_id, opts)
        selected_tools = set(selected.values())
        all_source_tools = set(LITERATURE_SOURCE_TOOLS.values())
        filtered = [tool_name for tool_name in enabled_tools if tool_name not in all_source_tools or tool_name in selected_tools]
        selected_sources = set(selected)
        if not selected_sources & LITERATURE_FETCH_SOURCES:
            filtered = [tool_name for tool_name in filtered if tool_name != 'WebFetch']
        return filtered

    @staticmethod
    def _search_tool_result_succeeded(success: bool, output: str) -> bool:
        return bool(success) and (not LITERATURE_SEARCH_ERROR_RE.search(str(output or '').strip()))

    @classmethod
    def _search_tool_failure_kind(cls, success: bool, output: str) -> str:
        """Classify retrieval failures so outages do not become science edits."""
        text = str(output or '').strip()
        if cls._search_tool_result_succeeded(success, text):
            return ''
        lowered = text.casefold()
        if any(marker in lowered for marker in ('not configured', 'no search api configured', 'http 401', 'http 403', 'api error: 401', 'api error: 403')):
            return 'configuration_error'
        if any((marker in lowered for marker in ('tool_schema_error', 'missing required argument', 'query error', 'invalid query', 'bad request', 'http 400', 'api error: 400', 'api error 400'))):
            return 'request_invalid'
        if any((marker in lowered for marker in ('transport error', 'api error: 429', 'api error 429', 'api error: 500', 'api error 500', 'api error: 502', 'api error 502', 'api error: 503', 'api error 503', 'api error: 504', 'api error 504', 'http 429', 'http 500', 'http 502', 'http 503', 'http 504', 'rate limit', 'too many requests', 'timed out', 'timeout', 'temporarily unavailable', 'connection reset', 'connection closed', 'connection aborted', 'peer closed', 'incomplete chunked read', 'bad gateway', 'service unavailable', 'readerror', 'connecterror', 'remoteprotocolerror'))):
            return 'platform_unavailable'
        if not success:
            return 'tool_failure'
        return 'retrieval_failure'

    async def _ensure_stage_search_evidence(self, run: WorkflowRun, node: WorkflowNode, research_direction: str, opts: dict, enabled_tools: list[str]) -> str:
        """Execute missing selected-source calls before literature/novelty synthesis."""
        source_tools = self._literature_source_tool_contract(node.id, opts)
        if not source_tools:
            return ''
        root = Path(run.project_path).expanduser().resolve()
        evidence_path = root / 'literature' / 'SEARCH_EVIDENCE.json'
        try:
            evidence = json.loads(evidence_path.read_text(encoding='utf-8'))
        except (OSError, UnicodeError, json.JSONDecodeError):
            evidence = {}
        stage = evidence.get('stages', {}).get(node.id, {}) if isinstance(evidence, dict) else {}
        usage = stage.get('source_usage') if isinstance(stage, dict) else {}
        missing_sources = [source for source in source_tools if not isinstance(usage, dict) or not isinstance(usage.get(source), dict) or usage[source].get('status') != 'used']
        if not missing_sources:
            return ''
        strategy = dict(opts.get('research_strategy') or {})
        year_from = int(strategy.get('literature_year_from') or 2017)
        year_to = int(strategy.get('literature_year_to') or time.gmtime().tm_year)
        max_results = max(3, min(8, int(strategy.get('literature_max_papers') or 35)))
        selected_idea = self._extract_selected_idea(root, '', research_direction)
        stage_focus = 'claim-level nearest prior work and competing mechanisms' if node.id == 'novelty' else 'systematic background and frontier methods'
        query = ' '.join((item.strip() for item in (research_direction, selected_idea if node.id == 'novelty' else '', stage_focus, f'{year_from} {year_to}') if item and item.strip()))[:1200]
        definitions = {definition.name: definition for definition in agent_engine._tool_definitions}
        trace: list[dict[str, Any]] = []
        summaries: list[str] = []
        for source in missing_sources:
            tool_name = source_tools[source]
            handler = agent_engine._tools.get(tool_name)
            called_at = time.time()
            args: dict[str, Any] = {'query': query}
            definition = definitions.get(tool_name)
            properties = definition.parameters.get('properties', {}) if definition and isinstance(definition.parameters, dict) else {}
            if 'max_results' in properties:
                args['max_results'] = max_results
            elif 'limit' in properties:
                args['limit'] = max_results
            success = False
            output = ''
            if handler is None:
                output = f'Required source tool is unavailable: {tool_name}'
            else:
                try:
                    pending = handler(**args)
                    value = await asyncio.wait_for(pending if inspect.isawaitable(pending) else asyncio.sleep(0, result=pending), timeout=30)
                    output = str(value or '')
                    success = self._search_tool_result_succeeded(True, output)
                except Exception as exc:
                    output = f'{type(exc).__name__}: {exc}'
            trace.append({'tool': tool_name, 'args': args, 'success': success, 'failure_kind': self._search_tool_failure_kind(success, output), 'output_preview': output[:500], 'called_at': called_at, 'finished_at': time.time()})
            summaries.append(f"- {source} via `{tool_name}` ({('used' if success else 'failed')}): " + output[:1200])
            await self._emit(run, 'workflow_source_preflight_call', {'node_id': node.id, 'source': source, 'tool': tool_name, 'success': success})
        self._persist_search_evidence(run, node, opts, enabled_tools, trace)
        return '\n'.join(summaries)

    def _persist_search_evidence(self, run: WorkflowRun, node: WorkflowNode, opts: dict, enabled_tools: list[str], tool_trace: list[dict[str, Any]]) -> Optional[Path]:
        runtime_path = Path(run.project_path).expanduser().resolve() / '.merak' / 'runs' / f'{run.id}.search-evidence.json'
        with path_lock(runtime_path):
            return self._persist_search_evidence_locked(run, node, opts, enabled_tools, tool_trace)

    def _persist_search_evidence_locked(self, run: WorkflowRun, node: WorkflowNode, opts: dict, enabled_tools: list[str], tool_trace: list[dict[str, Any]]) -> Optional[Path]:
        """Persist source use observed by the runtime, never model self-report."""
        source_tools = self._literature_source_tool_contract(node.id, opts)
        if not source_tools:
            return None
        calls: list[dict[str, Any]] = []
        tool_to_source = {tool_name: source for source, tool_name in source_tools.items()}
        for raw in tool_trace:
            tool_name = str(raw.get('tool') or '')
            source = tool_to_source.get(tool_name)
            if not source:
                continue
            calls.append({'source': source, 'tool': tool_name, 'args': raw.get('args'), 'success': bool(raw.get('success', False)), 'failure_kind': str(raw.get('failure_kind') or self._search_tool_failure_kind(bool(raw.get('success', False)), str(raw.get('output_preview') or ''))), 'output_preview': str(raw.get('output_preview') or '')[:500], 'called_at': float(raw.get('called_at') or time.time()), 'finished_at': float(raw.get('finished_at') or 0), 'runtime_observed': True})
        if node.id == 'lit':
            precollected = {str(item) for item in run.options.get('_precollected_literature_sources', [])}
            for source in source_tools:
                if source in precollected and (not any((item['source'] == source and item['success'] for item in calls))):
                    calls.append({'source': source, 'tool': 'workflow_context_ingestion', 'args': {'query': 'research_direction'}, 'success': True, 'output_preview': f'{source} context was collected into a project artifact before model synthesis.', 'called_at': time.time(), 'finished_at': time.time(), 'runtime_observed': True})
        root = Path(run.project_path).expanduser().resolve()
        path = root / 'literature' / 'SEARCH_EVIDENCE.json'
        runtime_path = root / '.merak' / 'runs' / f'{run.id}.search-evidence.json'
        path.parent.mkdir(parents=True, exist_ok=True)
        runtime_path.parent.mkdir(parents=True, exist_ok=True)
        payload: dict[str, Any] = {}
        for candidate in (runtime_path, path):
            try:
                candidate_payload = json.loads(candidate.read_text(encoding='utf-8'))
            except (OSError, UnicodeError, json.JSONDecodeError):
                continue
            if isinstance(candidate_payload, dict) and candidate_payload.get('run_id') == run.id:
                payload = candidate_payload
                break
        if not isinstance(payload, dict) or payload.get('run_id') != run.id:
            payload = {'schema_version': 1, 'run_id': run.id, 'selected_sources': list(source_tools), 'stages': {}}
        stages = payload.setdefault('stages', {})
        stage = stages.setdefault(node.id, {'attempts': []})
        attempts = stage.setdefault('attempts', [])
        attempts.append({'attempt': len(attempts) + 1, 'recorded_at': time.time(), 'enabled_tools': list(enabled_tools), 'source_tools': source_tools, 'calls': calls})
        stage['attempts'] = attempts[-20:]
        all_calls = [call for attempt in stage['attempts'] for call in attempt.get('calls', []) if isinstance(call, dict)]
        usage: dict[str, dict[str, Any]] = {}
        for source, tool_name in source_tools.items():
            source_calls = [call for call in all_calls if call.get('source') == source]
            successful = [call for call in source_calls if call.get('success') is True]
            usage[source] = {'selected': True, 'tool': tool_name, 'calls': len(source_calls), 'successful_calls': len(successful), 'failure_kinds': sorted({str(call.get('failure_kind') or '') for call in source_calls if str(call.get('failure_kind') or '')}), 'status': 'used' if successful else 'failed' if source_calls else 'not_used'}
        stage['source_usage'] = usage
        stage['complete'] = all((item['status'] == 'used' for item in usage.values()))
        payload['selected_sources'] = list(source_tools)
        payload['updated_at'] = time.time()
        atomic_write_json(runtime_path, payload)
        atomic_write_json(path, payload)
        return path

    def _workflow_stage_required_tools(self, node: WorkflowNode, project_path: str, skill_plan: Any, opts: Optional[dict]=None) -> set[str]:
        """Add runtime capabilities required by the node's artifact contract.
    
            A SKILL.md allowlist describes the standalone skill. Workflow ownership
            adds a second contract: when a node must create canonical artifacts it
            must receive the bounded file-authoring tools needed to do so. Without
            this merge a read-only review skill can enter an impossible revision
            loop while the gate waits for files it can never update.
            """
        required: set[str] = set()
        if self._required_artifacts_for_node(project_path, node.id):
            required.update({'Read', 'Write', 'Edit', 'Glob', 'Grep'})
        required.update(self._literature_source_tool_contract(node.id, opts).values())
        required.update({'figure': {'generate_figure', 'figure_manifest'}, 'compile': {'latex_compile'}, 'ppt': {'latex_compile'}}.get(node.id, set()))
        if node.id == 'figure':
            required.add('Skill')
        if node.id == 'exp-run' and (opts or {}).get('run_experiment') is True and (str((opts or {}).get('gpu_target') or 'local') == 'remote'):
            required.update({'watchdog_check', 'ssh_exec', 'ssh_deploy', 'ssh_sync'})
        if node.id == 'novelty' and (opts or {}).get('enable_patent_search'):
            required.add('patent_search')
        if getattr(skill_plan, 'specialists', None):
            required.add('Skill')
        return required

    @staticmethod
    def _workflow_disabled_tools(opts: Optional[dict]=None) -> set[str]:
        """Resolve integration tools that must be hidden for this workflow."""
        from ..services.workflow_tool_capabilities import disabled_workflow_tools
        return disabled_workflow_tools(opts)

    def _revision_runtime_signature(self, project_path: str, node_id: str, opts: dict) -> str:
        """Fingerprint the runtime capabilities that can remediate one node."""
        from ..services.skill_orchestrator import skill_orchestrator
        from ..services.skill_registry import skill_registry
        self._ensure_agent_tools()
        definition = next((item for item in self._get_default_nodes() if item.id == node_id), WorkflowNode(id=node_id, name=node_id, skill=''))
        plan = skill_orchestrator.select(definition.id, definition.skill, project_path, dict(opts or {}))
        metadata = skill_registry.get_skill(plan.primary)
        skill_digest = ''
        if metadata and metadata.file_path:
            try:
                skill_digest = hashlib.sha256(Path(metadata.file_path).read_bytes()).hexdigest()
            except OSError:
                skill_digest = ''
        services_root = Path(__file__).resolve().parents[1] / 'services'
        implementation_sources = {'exp-design': ('method_contract.py', 'research_quality.py'), 'exp-run': ('experiment_placeholders.py', 'simulation_policy.py'), 'results': ('node_risk_audit.py', 'research_specialists.py', 'experiment_placeholders.py', 'simulation_policy.py'), 'figure': ('figure_artifacts.py', 'figure_engine.py', 'experiment_placeholders.py', 'simulation_policy.py'), 'narrative': ('scientific_narrative.py',), 'paper': ('paper_drafting.py', 'paper_artifacts.py', 'paper_compiler.py'), 'review': ('paper_drafting.py', 'api_visual_reviewer.py'), 'audit': ('audit.py', 'node_risk_audit.py', 'simulation_policy.py'), 'compile': ('paper_compiler.py',), 'ppt': ('scientific_slides.py', 'paper_compiler.py')}
        implementation_paths = [services_root / filename for filename in implementation_sources.get(node_id, ())]
        from ..services.research_lifecycle_sources import lifecycle_source_paths
        implementation_paths.extend(lifecycle_source_paths(services_root, node_id))
        implementation_paths.extend(services_root.parent / 'utils' / name
                                    for name in ('atomic_write.py', 'runtime_source_root.py'))
        implementation_paths.extend(Path(__file__).with_name(name) for name in (
            'artifact_snapshot_ownership.py', 'engine_snapshot_paths.py',
            'accepted_phase_validation.py', 'dependency_reuse.py',
        ))
        implementation_paths.extend(services_root / name for name in (
            'specialist_inputs.py', 'specialist_plan.py', 'research_specialists.py',
        ))
        if node_id in {'exp-design', 'exp-run', 'results', 'figure', 'narrative', 'paper', 'review', 'audit', 'compile', 'ppt'}:
            implementation_paths.extend((services_root / 'planned_result_reuse.py', Path(__file__).with_name('engine_inputs.py')))
            implementation_paths.extend(services_root / name for name in ('simulation_figure_portfolio.py', 'simulation_paper_projection.py', 'simulation_render_bundle.py', 'simulation_publication_registry.py', 'planned_simulation_bindings.py'))
        if node_id in {'paper', 'review', 'audit', 'compile', 'ppt'}:
            implementation_paths.extend(services_root / name for name in ('latex_compile_execution.py', 'local_compile_process.py', 'windows_compile_job.py'))
        if node_id == 'figure':
            implementation_paths.extend(services_root / name for name in (
                'figure_semantic_projection.py', 'evaluation_design_svg.py',
                'scientific_plotting.py', 'scientific_plot_template.py',
                'figure_generation_transaction.py', 'figure_result_finalizer.py', 'figure_diagram_text.py',
            ))
        if node_id == 'results':
            implementation_paths.extend(services_root / name for name in (
                'node_execution_contract.py', 'results_execution_policy.py', 'skill_execution_trace.py',
                'skill_selection.py', 'simulation_asset_profile.py',
            ))
            implementation_paths.extend(Path(__file__).with_name(name) for name in (
                'results_runtime_execution.py', 'run_execution_node.py', 'node_gate_preparation.py',
                'revision_execution.py', 'engine_artifacts_a.py', 'engine_execution.py', 'engine_inputs.py',
                'simulation_result_analysis.py', 'simulation_report_contract.py',
            ))
        if node_id == 'paper':
            from ..services.paper_preparation_sources import paper_preparation_implementation_paths
            implementation_paths.extend(paper_preparation_implementation_paths(services_root))
        if node_id == 'ppt':
            from ..services.slide_contract_sources import slide_contract_implementation_paths
            implementation_paths.extend(slide_contract_implementation_paths(services_root))
        if node_id in {'review', 'audit'}:
            implementation_paths.append(Path(__file__).resolve().with_name('review_audit.py'))
        if node_id == 'review':
            from .review_contract_sources import review_contract_implementation_paths
            implementation_paths.extend(review_contract_implementation_paths(services_root))
        from ..services.scientific_contract_sources import scientific_contract_implementation_paths
        implementation_paths.extend(scientific_contract_implementation_paths(services_root, node_id))
        implementation_digests: dict[str, str] = {}
        for implementation_path in implementation_paths:
            try:
                implementation_digests[implementation_path.name] = hashlib.sha256(implementation_source_path(implementation_path).read_bytes()).hexdigest()
            except OSError:
                implementation_digests[implementation_path.name] = '<unavailable>'
        payload = {'version': WORKFLOW_TOOL_CONTRACT_VERSION, 'node_runtime_contract_version': NODE_RUNTIME_CONTRACT_VERSIONS.get(node_id, 1), 'implementation_sha256': implementation_digests, 'node_id': node_id, 'owner': plan.primary, 'owner_sha256': skill_digest, 'declared_tools': list(metadata.allowed_tools) if metadata else [], 'required_tools': sorted(self._workflow_stage_required_tools(definition, project_path, plan, opts)), 'registered_tools': sorted(agent_engine._tools), 'integration_options': {'illustration_mode': str((opts or {}).get('illustration_mode') or 'auto'), **{key: bool((opts or {}).get(key, False)) for key in ('enable_gemini', 'enable_gpt_image', 'enable_zotero', 'enable_obsidian', 'enable_patent_search', 'run_experiment')}}, 'revision_policy': {'max_revision_rounds': normalize_revision_rounds((opts or {}).get('max_revision_rounds'))}}
        digest = hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode('utf-8')).hexdigest()[:24]
        return f'runtime:{digest}'


    def _configure_agent_limits(self, session, node_id: str, effort: str, project_path: str) -> None:
        """Apply hard per-node iteration and expensive-tool budgets."""
        configured_iterations = max(4, int(get_effort_config(effort).max_agent_iterations))
        session.max_iterations = configured_iterations
        session.tool_call_limits['Skill'] = 2
        if node_id != 'figure':
            return
        from ..services.scientific_evidence import scientific_evidence_service
        try:
            has_proven_metrics, _, _ = scientific_evidence_service.validate_executed_metrics(project_path)
        except Exception as exc:
            logger.warning('Figure evidence scan failed; using conservative generation budget', project_path=project_path, error=str(exc))
            has_proven_metrics = False
        planned_count = 0
        for candidate in (Path(project_path) / 'figures' / 'FIGURE_SPECS.json', Path(project_path) / 'figures' / 'SCIENTIFIC_ASSET_PLAN.json'):
            try:
                payload = json.loads(candidate.read_text(encoding='utf-8-sig'))
            except (OSError, UnicodeError, json.JSONDecodeError):
                continue
            records = payload.get('figures') or payload.get('specs') or payload.get('assets')
            if isinstance(records, list):
                planned_count = len([item for item in records if isinstance(item, dict) and ('kind' not in item or item.get('kind') == 'figure')])
                if planned_count:
                    break
        planned_count = max(3, planned_count)
        iteration_budget = max(16, min(28, 4 + 4 * planned_count))
        session.max_iterations = min(configured_iterations, iteration_budget)
        session.tool_call_limits['generate_figure'] = min(12, max(6 if has_proven_metrics else 4, planned_count * 2))
        session.tool_call_limits['Skill'] = min(8, planned_count + 2)

