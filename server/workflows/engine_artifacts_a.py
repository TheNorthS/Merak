"""artifacts a workflow engine responsibilities."""

# ruff: noqa: F403, F405
from .engine_context import *

class ArtifactsAMixin:
    @staticmethod
    def _simulation_result_rows(path: Path) -> list[dict[str, str]]:
        try:
            with path.open('r', encoding='utf-8-sig', newline='') as handle:
                return [{str(key): str(value or '') for key, value in row.items()} for row in csv.DictReader(handle)]
        except (OSError, csv.Error):
            return []

    def _ensure_planned_results_analysis(self, run: WorkflowRun, research_direction: str, result: str='') -> str:
        """Write a deterministic, claim-aware no-run analysis.
    
            A model is not needed to restate that no experiment was requested. Keeping
            this path deterministic prevents placeholder runs from consuming revision
            rounds and guarantees every claim has a concrete future evidence request.
            """
        from .results_runtime_execution import runtime_results_contract
        contract = runtime_results_contract(run, run.options)
        if contract.kind != 'runtime_owned':
            raise ValueError('Measured or imported evidence cannot be overwritten by planned-result analysis.')
        if contract.runtime_service == 'deterministic_benchmark_analysis':
            return self._ensure_simulation_results_analysis(run, research_direction, result=result)
        root = Path(run.project_path).resolve()
        selected_path = root / 'ideas' / 'SELECTED_IDEA.json'
        method_path = root / 'experiments' / 'METHOD_CONTRACT.json'
        blueprint_path = root / 'experiments' / 'IMPLEMENTATION_BLUEPRINT.json'
        analysis_path = root / 'experiments' / 'results' / 'analysis.md'
        try:
            selected = json.loads(selected_path.read_text(encoding='utf-8-sig'))
        except (OSError, json.JSONDecodeError):
            selected = {}
        try:
            method = json.loads(method_path.read_text(encoding='utf-8-sig'))
        except (OSError, json.JSONDecodeError):
            method = {}
        try:
            blueprint = json.loads(blueprint_path.read_text(encoding='utf-8-sig'))
        except (OSError, json.JSONDecodeError):
            blueprint = {}
        implementation_family = str(blueprint.get('implementation_family') or 'computational_general').strip().casefold()
        runtime_requirements = {'machine_learning': ['Resolved run/configuration ID, source/data/split/preprocessing hashes, replicate seed, environment, and checkpoint identity.', 'Unit-level predictions and paired split/replicate outputs when uncertainty or significance is claimed.', 'Locked controls, mechanism tests, failure slices, calibration/resource records, and retained failed attempts.'], 'formal_verification': ['Checker/build ID, formal source and assumption-registry hashes, solver options, precision, resource limits, and certificate identity.', 'Per-obligation verdicts that distinguish proved, checked, bounded-tested, falsified, timeout, and unknown.', 'Counterexamples/boundary instances, coverage limits, complexity facts, and retained failed obligations.'], 'external_protocol': ['Study/protocol/registry or corpus snapshot ID, cohort/site/batch identity, analysis version, and decision ledger.', 'Independent-unit estimates or traceable theme/excerpt records with missingness/exclusion/adjudication provenance.', 'Prespecified references, sensitivity/subgroup/negative-case analyses, deviations, and retained failed or ambiguous observations.'], 'computational_general': ['Resolved run/configuration ID, source/input/scenario/parameter-grid hashes, precision, environment, and replicate identity where stochastic.', 'Per-instance or per-analysis-unit outputs supporting uncertainty, stability, and paired comparisons when claimed.', 'Locked references, mechanism/sensitivity/boundary tests, resource records, and retained divergent/failed runs.']}.get(implementation_family)
        if runtime_requirements is None:
            runtime_requirements = ['Hash-linked execution identity and resolved scientific configuration.', 'Independent-unit evidence for every reported outcome.', 'Reference, sensitivity, failure, and provenance records.']
        follow_up = {'machine_learning': ['Validate leakage-safe splits and preprocessing boundaries.', 'Run the accepted method, matched controls, mechanism tests, and registered stress/calibration analyses.'], 'formal_verification': ['Validate definitions, assumptions, obligation registry, checker build, and boundary instances.', 'Run proof checks, reference constructions, bounded counterexample search, and complexity/scaling analysis.'], 'external_protocol': ['Validate eligibility/sampling, independent units, estimand or coding contract, missingness, and protocol provenance.', 'Run the primary analysis plus prespecified adjustment, subgroup, sensitivity, triangulation, or negative-case checks.'], 'computational_general': ['Validate inputs, scenarios, parameter ranges, analysis units, numerical settings, and contamination controls.', 'Run the primary algorithm/reference comparison plus mechanism, sensitivity, stability, boundary, and resource analyses.']}.get(implementation_family) or ['Validate every frozen input and decision contract.', 'Run the primary analysis, references, mechanism tests, and robustness checks.']
        title = str(selected.get('title') or research_direction or 'Selected research idea').strip()
        hypothesis = str(selected.get('hypothesis') or 'No frozen hypothesis is available.').strip()
        claims = [item for item in selected.get('claims') or [] if isinstance(item, dict)]
        evidence_by_claim = {str(item.get('idea_claim_id') or ''): item for item in method.get('claim_evidence_plan') or [] if isinstance(item, dict)}
        lines = ['# Planned Result Analysis (NOT EVIDENCE)', '', 'This report is generated because scientific experiment execution was disabled.', 'It contains no measured performance, no fabricated sample count, and no inferential result.', '', '## Research Contract', f"- Direction: {research_direction or '(not declared)'}", f'- Accepted idea: {title}', f'- Hypothesis to be tested (PENDING): {hypothesis}', '- Evidence status: planned / pending', '', '## Claim Status', '', '| Claim | Current status | Decisive evidence still required | Falsification boundary |', '|---|---|---|---|']
    
        def prospective_cell(values: list[Any], *, prefix: str, fallback: str) -> str:
            entries = []
            for value in values:
                clean = ' '.join(str(value or '').replace('|', '/').split())
                if clean:
                    entries.append(prefix + clean)
            return '; '.join(entries) or fallback
        if claims:
            for claim in claims:
                claim_id = str(claim.get('id') or 'C?')
                plan = evidence_by_claim.get(claim_id, {})
                outcomes = prospective_cell(list(plan.get('outcomes') or []), prefix='To be tested: ', fallback='To be tested: run the prespecified comparison.')
                failures = prospective_cell(list(plan.get('failure_conditions') or []), prefix='The claim would be rejected if ', fallback='The claim would be rejected if the result is negative or inconclusive.')
                lines.append(f'| {claim_id} | PENDING | {outcomes} | {failures} |')
        else:
            lines.append('| C1 | PENDING | Execute the declared primary comparison. | Narrow or reject the claim if it fails. |')
        lines.extend(['', '## Required Runtime Evidence', '', '- Hash-linked successful execution or verification event for every scientific result artifact.', *[f'- {item}' for item in runtime_requirements], '- Failure cases, boundary conditions, alternative explanations, and limitations must be analyzed before any confirmatory wording.', '', '## Planned Follow-up', '', '1. Run the preflight command from experiments/RUN_SPEC.json.', f'2. {follow_up[0]}', f'3. {follow_up[1]}', '4. Replace only the planned schemas with runtime-owned artifacts, then rerun this analysis.', '', '## Explicit Prohibition', '', 'Blank template rows, dry-run output, and code-check output are not scientific evidence.'])
        analysis_path.parent.mkdir(parents=True, exist_ok=True)
        existing = analysis_path.read_text(encoding='utf-8', errors='replace') if analysis_path.is_file() else ''
        desired = '\n'.join(lines) + '\n'
        if existing != desired:
            atomic_write_text(analysis_path, desired)
        return result or 'No experiment requested; deterministic planned-result analysis written.'

    @staticmethod
    def _verified_figure_skill_invocation(root: Path, asset_id: str, expected_skill: str) -> bool:
        """Verify that a persisted source came from the assigned skill session."""
        if not asset_id or not expected_skill:
            return False
        sessions = root / '.merak' / 'agent-sessions'
        if not sessions.is_dir():
            return False
        for path in sorted(sessions.glob('*.json'), key=lambda item: item.stat().st_mtime, reverse=True):
            try:
                payload = json.loads(path.read_text(encoding='utf-8-sig'))
            except (OSError, UnicodeError, json.JSONDecodeError):
                continue
            context_key = str(payload.get('context_key') or '')
            lineage = [item for item in context_key.split(':', 1)[-1].split('>') if item]
            calls = dict(payload.get('tool_call_counts') or {})
            if not lineage or lineage[-1] != expected_skill or int(calls.get('generate_figure') or 0) < 1:
                continue
            message_text = json.dumps(payload.get('messages') or [], ensure_ascii=False)
            if asset_id in message_text:
                return True
        return False

    async def _ensure_figure_artifacts(self, run: WorkflowRun, result: str, research_direction: str, *, target_asset_ids: Optional[set[str]]=None) -> None:
        """Build source-grounded deterministic figures and reconcile editable assets."""
        from ..services.figure_artifacts import figure_artifact_registry
        from ..services.scientific_assets import scientific_asset_service
        root = Path(run.project_path).resolve()
        from ..services.paper_plan_runtime import require_current_model_plan
        require_current_model_plan(root)
        figures_root = root / 'figures'
        (figures_root / 'diagrams').mkdir(parents=True, exist_ok=True)
        (figures_root / 'plots').mkdir(parents=True, exist_ok=True)
        requested_evidence_mode = str(run.options.get('non_experiment_evidence_mode') or '')
        if run.options.get('run_experiment') is not True and requested_evidence_mode == 'synthetic_preview':
            await self._ensure_planned_result_templates(run, research_direction)
        asset_plan = scientific_asset_service.build_plan(root, experiment_requested=run.options.get('run_experiment') is True, requested_evidence_mode=requested_evidence_mode, illustration_mode=str(run.options.get('illustration_mode') or 'auto'), direction=research_direction, target_venue=str(run.options.get('target_venue') or ''), research_family=str(run.options.get('research_family') or ''), study_archetype=str(run.options.get('study_archetype') or ''))
        selected_ids = {str(item).strip() for item in target_asset_ids or set() if str(item).strip()}
        from ..services.figure_spec_repository import persist_figure_specs
        planned_specs = persist_figure_specs(root, asset_plan)
        from ..services.simulation_publication_attestation import attest_existing_simulation_figures
        attest_existing_simulation_figures(root)
        planned_assets = {str(item.get('id') or ''): dict(item) for item in asset_plan.get('assets', []) if isinstance(item, dict) and str(item.get('id') or '').strip()}
        from ..services.figure_engine import figure_engine
        from ..services.figure_routing import expected_source_extensions
        existing_entries = {str((item.get('metadata') or {}).get('semantic_key') or item.get('id') or ''): item for item in figure_artifact_registry.load(figures_root).get('figures', []) if isinstance(item, dict)}
        from ..services.deterministic_figure_builder import ensure_evaluation_design
        existing_entries = await ensure_evaluation_design(
            self, run, figures_root, planned_specs, asset_plan,
            selected_ids, figure_artifact_registry,
        )
        for spec in planned_specs:
            asset_id = str(spec.get('id') or '').strip()
            if selected_ids and asset_id not in selected_ids:
                continue
            backend = str(spec.get('recommended_backend') or '').strip()
            if not asset_id:
                continue
            entry = existing_entries.get(asset_id, {})
            metadata = dict(entry.get('metadata') or {})
            already_rendered = bool(entry.get('output_path'))
            source = next((directory / f'{asset_id}{extension}' for directory in (figures_root, figures_root / 'diagrams', figures_root / 'plots') for extension in expected_source_extensions(backend) if (directory / f'{asset_id}{extension}').is_file() and (directory / f'{asset_id}{extension}').stat().st_size > 0), None)
            renderer_repair_issues: list[str] = []
            if backend.casefold() == 'rich_svg' and source is not None and (source.suffix.casefold() == '.svg'):
                renderer_repair_issues.extend(figure_artifact_registry.rich_svg_source_issues(source))
                preview_value = str(metadata.get('preview_path') or '').strip()
                preview = (root / preview_value).resolve() if preview_value and (not Path(preview_value).is_absolute()) else Path(preview_value).expanduser().resolve() if preview_value else source.with_suffix('.png')
                if preview.is_file():
                    renderer_repair_issues.extend(figure_artifact_registry.rich_svg_render_issues(preview))
            elif source is not None and source.suffix.casefold() in {'.mmd', '.mermaid'}:
                preview_value = str(metadata.get('preview_path') or '').strip()
                preview = (root / preview_value).resolve() if preview_value and (not Path(preview_value).is_absolute()) else Path(preview_value).expanduser().resolve() if preview_value else source.with_suffix('.png')
                if preview.is_file():
                    renderer_repair_issues.extend(figure_artifact_registry.raster_layout_issues(preview))
            if already_rendered and (not renderer_repair_issues):
                continue
            if source and source.suffix.casefold() in {'.py', '.svg', '.json', '.mmd', '.mermaid', '.drawio', '.dio', '.excalidraw'}:
                refresh_metadata = {**dict(spec), 'semantic_key': asset_id, 'managed_by': 'merak', 'paper_selected': True, 'manuscript_eligible': True, 'style_profile': str((asset_plan.get('publication_style') or {}).get('visual_standard') or 'field-adaptive-accessible-vector-v3')}
                expected_skill = str(spec.get('recommended_skill') or '').strip()
                if self._verified_figure_skill_invocation(root, asset_id, expected_skill):
                    refresh_metadata.update({'generator_skill': expected_skill, 'skill': expected_skill, 'skill_invocation_verified': True})
                refresh = await figure_engine.refresh_editable_source(source, metadata_override=refresh_metadata, description_override=str(spec.get('caption') or asset_id))
                await self._emit(run, 'figure_source_reconciled', {'node_id': 'figure', 'asset_id': asset_id, 'source_path': str(source), 'success': bool(refresh.get('success')), 'output_path': refresh.get('output_path'), 'error': str(refresh.get('error') or ''), 'renderer_repair_issues': renderer_repair_issues, 'auto_open': False})
        manifest_path = figure_artifact_registry.manifest_path(figures_root)
        if not manifest_path.exists():
            figure_artifact_registry.reconcile(figures_root)
        figure_artifact_registry.reconcile(figures_root)
        figure_artifact_registry.prune_semantic_duplicates(figures_root)
        payload = figure_artifact_registry.curate_to_plan(figures_root, {str(item.get('id') or '') for item in asset_plan.get('assets', []) if isinstance(item, dict) and item.get('kind') == 'figure' and (str(item.get('generation_policy') or 'generate').casefold() != 'skip')}, evidence_mode=str(asset_plan.get('evidence_mode') or 'design_only'), planned_assets=planned_assets)
        for item in payload.get('figures', []):
            metadata = dict(item.get('metadata') or {})
            if metadata.get('paper_selected') is False:
                continue
            await self._emit(run, 'figure_artifact_generated', {'node_id': 'figure', 'figure_type': item.get('type'), 'description': item.get('description'), 'output_path': item.get('output_path'), 'preview_path': metadata.get('preview_path'), 'source_path': item.get('source_path'), 'manifest_path': str(manifest_path), 'reused': bool(metadata.get('reused')), 'auto_open': False})

    async def _ensure_paper_artifacts(self, run: WorkflowRun, result: str, research_direction: str) -> str:
        """Compile and verify the accepted staged manuscript."""
        from ..services.paper_artifacts import paper_artifact_builder
        from ..services.paper_budget import paper_budget_service
        from ..services.paper_compiler import paper_compiler
        from ..services.paper_drafting import paper_drafting_service
        innovation_mode = str(run.options.get('research_mode') or 'from_scratch') == 'paper_code_innovation'
        from ..services.paper_preparation_errors import prepare_paper_evidence
        from ..services.paper_print_projection import restore_print_entrypoint
        restore_print_entrypoint(run.project_path)
        from .paper_method_presentation import refresh_method_presentation
        await refresh_method_presentation(run)
        evidence = prepare_paper_evidence(run.project_path, research_direction)
        assembly_refresh = paper_drafting_service.refresh_deterministic_assembly(run.project_path)
        if assembly_refresh.get('passed'):
            await self._emit(run, 'paper_assembly_refreshed', {'node_id': 'paper', 'main_path': str(assembly_refresh.get('main_path') or ''), 'main_sha256': str(assembly_refresh.get('main_sha256') or '')})
        mode = 'staged-section-draft'
        gate = self._paper_acceptance_gate(run.project_path, require_innovation=innovation_mode, require_staged=True, paper_options=run.options)
        if not gate.get('accepted'):
            from ..services.paper_acceptance_errors import PaperAcceptanceError

            raise PaperAcceptanceError(gate)
        paper_dir = Path(run.project_path) / 'paper'
        repaired_packages = paper_compiler.repair_common_source_dependencies(paper_dir, 'main.tex')
        if repaired_packages:
            await self._emit(run, 'latex_dependency_repaired', {'node_id': 'paper', 'packages': repaired_packages, 'source_path': str(paper_dir / 'main.tex')})
        from ..services.paper_print_repair import compile_print_verified_paper
        compile_result = await compile_print_verified_paper(
            paper_compiler, run.project_path,
            on_repair=lambda data: self._emit(run, 'paper_print_layout_repaired', {'node_id': 'paper', **data}),
        )
        if not gate.get('accepted') or not compile_result.success:
            errors = self._compile_failure_summary(compile_result)
            raise RuntimeError(f'Paper compile verification failed: {errors}')
        budget = paper_budget_service.load(run.project_path)
        revision_rounds: list[dict] = []
    
        async def on_page_revision_event(event):
            data = event.data if isinstance(event.data, dict) else {'text': str(event.data or '')}
            if event.type == 'tool_call':
                await self._emit(run, 'agent_tool_call', {'node_id': 'paper', 'tool': data.get('name', ''), 'args': str(data.get('args', ''))[:400]})
            elif event.type == 'tool_result':
                await self._emit(run, 'agent_tool_result', {'node_id': 'paper', 'tool': data.get('name', ''), 'success': data.get('success', True), 'output': str(data.get('output', ''))[:600]})
            elif event.type == 'step':
                await self._emit(run, 'agent_step', {'node_id': 'paper', **data})
            elif event.type == 'status':
                await self._emit(run, 'agent_status', {'node_id': 'paper', **data})
            elif event.type == 'text' and data.get('text'):
                await self._emit(run, 'agent_output', {'node_id': 'paper', 'text': str(data['text'])[:1200]})
        page_warning = None
        if budget and (not budget.contains(compile_result.pages)):
            page_warning = f'Compiled paper has {compile_result.pages} pages; the preferred range is {budget.minimum_pages}-{budget.maximum_pages}. Scientific completeness takes priority, so this soft target does not block the workflow.'
            await self._emit(run, 'paper_page_target_missed', {'node_id': 'paper', 'actual_pages': compile_result.pages, 'minimum_pages': budget.minimum_pages, 'maximum_pages': budget.maximum_pages, 'warning': page_warning})
        page_contract = None
        if budget:
            page_contract = {**budget.to_dict(), 'actual_pages': compile_result.pages, 'soft_target': True, 'within_preferred_range': budget.contains(compile_result.pages), 'warning': page_warning, 'revision_rounds': revision_rounds}
        build_record = {'schema': 1, 'generated_at': time.time(), 'mode': mode, 'evidence_mode': evidence.evidence_mode, 'submission_eligible': evidence.submission_eligible, 'manuscript_class': 'synthetic_preview' if evidence.synthetic_preview else 'submission_candidate' if evidence.submission_eligible else 'scientific_draft', 'research_mode': str(run.options.get('research_mode') or 'from_scratch'), 'reference_snapshot_id': str(run.options.get('reference_snapshot_id') or ''), 'quality_gate': gate, 'compile': {'success': True, 'pdf_path': compile_result.pdf_path, 'pages': compile_result.pages, 'compile_time_ms': compile_result.compile_time_ms, 'warning_count': len(compile_result.warnings)}, 'page_contract': page_contract, 'table_manifest': 'paper/tables/TABLE_MANIFEST.json', 'figure_manifest': 'figures/FIGURE_MANIFEST.json', 'evidence_snapshot': 'paper/EVIDENCE_SNAPSHOT.json'}
        build_path = paper_dir / 'PAPER_BUILD.json'
        from ..services.paper_build_record import refresh_build_record
        if not refresh_build_record(paper_dir, 'PAPER_BUILD.json', 'main.pdf', pages=compile_result.pages,
                                    compile_time_ms=compile_result.compile_time_ms, warning_count=len(compile_result.warnings)):
            raise RuntimeError('Compiled manuscript cannot be bound to its current source and PDF artifacts')
        # Bind actual current compiler outputs before adding workflow metadata;
        # replacing this record with a summary would erase downstream readiness.
        build_record['compile'] = json.loads(build_path.read_text(encoding='utf-8-sig'))['compile']
        atomic_write_json(build_path, build_record)
        final_gate = self._paper_acceptance_gate(run.project_path, require_innovation=innovation_mode, require_page_budget=True, require_staged=True, paper_options=run.options)
        if not final_gate.get('accepted'):
            raise RuntimeError('Final paper gate failed after compile: ' + str(final_gate.get('summary') or final_gate.get('reason')))
        gate = final_gate
        await self._emit(run, 'paper_artifact_repaired', {'node_id': 'paper', 'mode': mode, 'paper_path': str(paper_dir / 'main.tex'), 'pdf_path': compile_result.pdf_path, 'pages': compile_result.pages, 'target_pages': budget.target_pages if budget else None, 'table_manifest': str(paper_dir / 'tables' / 'TABLE_MANIFEST.json'), 'figure_manifest': str(Path(run.project_path) / 'figures' / 'FIGURE_MANIFEST.json')})
        return result + chr(10) * 2 + f'MERAK paper verification: {mode}; ' + f"{gate.get('summary', '')}; compiled pages={compile_result.pages}."

    def _extract_selected_idea(self, root: Path, model_summary: str, research_direction: str) -> str:
        """Pick a concrete idea without asking the user when workflow auto-proceed is enabled."""
        selected_contract = root / 'ideas' / 'SELECTED_IDEA.json'
        if selected_contract.is_file():
            try:
                payload = json.loads(selected_contract.read_text(encoding='utf-8'))
                title = str(payload.get('title') or '').strip() if isinstance(payload, dict) else ''
                if title:
                    return title[:240]
            except (OSError, UnicodeError, json.JSONDecodeError):
                pass
        canonical_patterns = ('(?im)^\\s*(?:#{1,5}\\s*)?(?:recommended\\s+top\\s*[- ]?1|final\\s+recommendation|selected\\s+idea|auto-selected\\s+idea|最终推荐|首选\\s*idea|最高优先级(?:为|是))\\s*[:：\\-]\\s*[\\"“]?([^，。；;\\n\\"”]{8,180})', '(?im)^\\s*(?:推荐选择|推荐采用)\\s*[\\"“]?([^，。；;\\n\\"”]{8,180})', '(?im)^\\s*(?:top\\s*[- ]?1|rank(?:ed)?\\s*1|排名\\s*(?:第)?\\s*1)\\s*(?:idea)?\\s*[:：\\-（(]\\s*([^）)\\n|]{8,180})', '(?m)^\\s*\\|\\s*1\\s*\\|\\s*([^|\\n]{8,180})\\|', '(?im)^\\s*#{1,4}\\s*(?:idea\\s*)?1\\s*[.、:：\\-]\\s*([^\\n]{8,180})$')
        for relative in ('ideas/novelty_report.md', 'ideas/ideas.md', 'ideas/COMPACT_IDEA_CANDIDATES.md'):
            canonical = root / relative
            if not canonical.is_file():
                continue
            content = canonical.read_text(encoding='utf-8', errors='replace')
            for pattern in canonical_patterns:
                match = re.search(pattern, content)
                if match:
                    return match.group(1).strip().strip('*_ ')
        for pattern in ('(?:最高优先级(?:为|是)|auto-selected idea\\s*[:：]|selected idea\\s*[:：])\\s*[\\"“]?([^，。；;\\n\\"”]{8,180})', '(?:推荐选择|推荐采用)\\s*[\\"“]?([^，。；;\\n\\"”]{8,180})', '(?:top\\s*[- ]?1|rank(?:ed)?\\s*1|排名\\s*(?:第)?\\s*1)\\s*(?:idea)?\\s*[:：\\-（(]\\s*([^）)\\n|]{8,180})'):
            match = re.search(pattern, model_summary, flags=re.IGNORECASE)
            if match:
                return match.group(1).strip().strip('`*_ ')
        for rel in ('ideas/novelty_report.md', 'ideas/ideas.md', 'ideas/COMPACT_IDEA_CANDIDATES.md'):
            path = root / rel
            if not path.exists():
                continue
            try:
                content = path.read_text(encoding='utf-8', errors='replace')
                for pattern in ('(?im)(?:top\\s*[- ]?1|rank(?:ed)?\\s*1|排名\\s*(?:第)?\\s*1)\\s*(?:idea)?\\s*[:：\\-（(]\\s*([^）)\\n|]{8,180})', '(?m)^\\s*\\|\\s*1\\s*\\|\\s*([^|\\n]{8,180})\\|', '(?im)^\\s*#{1,4}\\s*(?:idea\\s*)?1\\s*[.、:：\\-]\\s*([^\\n]{8,180})$'):
                    match = re.search(pattern, content)
                    if match:
                        return match.group(1).strip().strip('`*_ ')
                for line in content.splitlines():
                    clean = line.strip().strip('#*-| ')
                    lowered = clean.lower()
                    if len(clean) >= 12 and (not lowered.startswith(('rank', '---', 'idea |', 'research ideas', 'project direction', 'source basis', 'generation policy', 'sorting', 'overview', 'novelty report', '新颖性', 'executive summary', 'overall assessment', '总体判断', '推荐结论', 'candidate ideas'))):
                        return clean[:240]
            except Exception:
                continue
        for line in model_summary.splitlines():
            clean = line.strip().strip('#*-| ')
            if len(clean) >= 12 and '请选择' not in clean and ('请告诉' not in clean):
                return clean[:240]
        return research_direction[:240]

    def _required_artifacts_for_node(self, project_path: str, node_id: str) -> list[Path]:
        """Canonical artifacts shared with the project scaffold and node prompts."""
        from ..services.project_scaffold import get_workflow_artifact_contract
        contract = get_workflow_artifact_contract(project_path, node_id)
        return [Path(path) for path in contract.get('required', [])]

    def _primary_artifact_for_node(self, project_path: str, node_id: str) -> str:
        from ..services.project_scaffold import get_workflow_artifact_contract
        return str(get_workflow_artifact_contract(project_path, node_id).get('primary') or project_path)

    def _gate_requirements_for_node(self, run: WorkflowRun, node_id: str) -> list[Path]:
        """Resolve the exact artifact set used by freshness and acceptance checks."""
        requirements = self._required_artifacts_for_node(run.project_path, node_id)
        options = dict(run.options or {})
        root = Path(run.project_path).resolve()
        if node_id == 'lit':
            sources = {str(item) for item in dict(options.get('research_strategy') or {}).get('literature_sources', [])}
            if options.get('enable_zotero') and 'zotero' in sources:
                requirements.append(root / 'literature' / 'zotero_context.json')
            if options.get('enable_obsidian') and 'obsidian' in sources:
                requirements.append(root / 'literature' / 'obsidian_context.json')
        if node_id == 'novelty' and options.get('enable_patent_search'):
            requirements.append(root / 'ideas' / 'patent_prior_art.json')
        if node_id == 'exp-design':
            if options.get('staged_experiment_implementation') is True:
                requirements.extend([root / 'experiments' / 'IMPLEMENTATION_BLUEPRINT.json', root / 'experiments' / 'IMPLEMENTATION_BUILD.json'])
        if node_id == 'exp-run' and options.get('run_experiment') is not True:
            requirements = [root / 'experiments' / 'src', root / 'experiments' / 'configs', root / 'experiments' / 'results' / 'templates' / 'PLANNED_RESULT_MANIFEST.json']
        return list(dict.fromkeys((path.resolve() for path in requirements)))
