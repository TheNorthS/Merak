"""inputs workflow engine responsibilities."""

# ruff: noqa: F403, F405
from .engine_context import *
from ..services.figure_spec_repository import persist_figure_specs
from ..services.scientific_scene import method_scene_authoring_example

class InputsMixin:
    async def _ensure_planned_result_templates(self, run: WorkflowRun, direction: str, force: bool=False) -> dict:
        """Materialize the canonical skipped-experiment templates before downstream agents read them."""
        from ..services.experiment_placeholders import experiment_placeholder_service
        from ..services.project_scaffold import get_convention_paths
        from ..services.planned_result_reuse import planned_result_evidence_mode, resolve_planned_result_reuse
        paths = get_convention_paths(run.project_path)
        requested_mode = planned_result_evidence_mode(run.options)
        expected_input_bundle_sha256 = experiment_placeholder_service.input_bundle_sha256(run.project_path, direction, evidence_mode=requested_mode, target_venue=str(run.options.get('target_venue') or ''), research_family=str(run.options.get('research_family') or ''), study_archetype=str(run.options.get('study_archetype') or ''))
        required = [Path(paths['planned_result_manifest']), Path(paths['planned_result_readme']), Path(paths['planned_main_comparison']), Path(paths['planned_ablation']), Path(paths['planned_robustness']), Path(paths['planned_result_tables_tex']), Path(run.project_path) / 'experiments' / 'results' / 'templates' / 'calibration_risk_coverage.csv', Path(run.project_path) / 'experiments' / 'results' / 'templates' / 'efficiency.csv', Path(run.project_path) / 'figures' / 'previews' / 'calibration_risk_coverage_preview.py', Path(run.project_path) / 'paper' / 'PUBLICATION_STYLE.json']
        if requested_mode == 'synthetic_preview':
            simulated_data = Path(run.project_path) / 'experiments' / 'results' / 'simulated'
            simulated_figures = Path(run.project_path) / 'figures' / 'simulated'
            simulation_manifest_path = simulated_data / 'SIMULATION_MANIFEST.json'
            required.extend([simulation_manifest_path, Path(run.project_path) / 'paper' / 'tables' / 'synthetic_preview_results.tex', Path(run.project_path) / 'paper' / 'synthetic_preview_figures.tex', *(simulated_data / name for name in ('main_comparison.csv', 'ablation.csv', 'training_dynamics.csv', 'robustness.csv', 'error_analysis.csv', 'calibration.csv', 'efficiency.csv', 'claim_evidence.csv')), *(simulated_figures / f'{stem}{suffix}' for stem in ('simulated_main_comparison', 'simulated_ablation', 'simulated_training_dynamics', 'simulated_robustness', 'simulated_error_analysis', 'simulated_calibration', 'simulated_efficiency') for suffix in ('.py', '.pdf', '.svg', '.png'))])
        from ..services.evidence_versions import EvidenceVersionRequired
        try:
            generated, planned = resolve_planned_result_reuse(
                Path(run.project_path).resolve(), required, mode=requested_mode, input_hash=expected_input_bundle_sha256,
                target_venue=str(run.options.get('target_venue') or 'unspecified'), force=force,
                frozen_authority=run.options.get('frozen_benchmark_authority'),
            )
        except EvidenceVersionRequired:
            if not run.options.get('_evidence_version_approval'):
                raise
            from .evidence_version_request import produce_approved_version
            from .evidence_producer_gate import require_evidence_producer_ready
            require_evidence_producer_ready(run.project_path, run.options)
            planned = await produce_approved_version(run, direction)
            generated = False
            await self._emit(run, 'evidence_version_published', {'version_id': planned.get('version_id'), 'archive': planned.get('archive')})
        if generated:
            from .evidence_producer_gate import require_evidence_producer_ready
            require_evidence_producer_ready(run.project_path, run.options)
            planned = await experiment_placeholder_service.ensure(run.project_path, direction, evidence_mode=requested_mode, target_venue=str(run.options.get('target_venue') or ''), research_family=str(run.options.get('research_family') or ''), study_archetype=str(run.options.get('study_archetype') or ''))
            await self._emit(run, 'planned_result_templates_generated', {'node_id': run.checkpoint_node_id or 'preflight', 'manifest_path': planned.get('manifest_path'), 'components': planned.get('components', []), 'robustness_axis': planned.get('robustness_axis', '')})
        elif requested_mode == 'synthetic_preview':
            from ..services.simulation_figure_refresh import refresh_existing_simulation_figures
            from ..services.simulation_paper_projection import refresh_simulation_paper_projection
            from ..services.simulation_table_publication_refresh import refresh_simulation_publication_tables

            refreshed = await refresh_existing_simulation_figures(Path(run.project_path))
            table_changed = refresh_simulation_publication_tables(Path(run.project_path))
            projection_changed = refresh_simulation_paper_projection(Path(run.project_path))
            if refreshed or projection_changed or table_changed:
                planned = json.loads(required[0].read_text(encoding='utf-8-sig'))
            if refreshed or projection_changed or table_changed:
                await self._emit(run, 'simulation_figure_rendering_refreshed', {
                    'node_id': run.checkpoint_node_id or 'preflight', 'asset_ids': refreshed,
                    'scientific_data_changed': False,
                    **({'paper_projection_changed': True} if projection_changed else {}),
                    **({'table_projection_changed': True} if table_changed else {}),
                })
        planned['manifest_path'] = str(required[0])
        run.options['planned_result_manifest'] = str(required[0])
        return planned

    async def _refresh_simulation_renderer_before_revalidation(
        self, run: WorkflowRun, direction: str
    ) -> bool:
        """Refresh producer-owned rendering before accepted owner validation."""
        from .simulation_render_refresh import refresh_simulation_renderer

        return await refresh_simulation_renderer(self, run, direction)

    @staticmethod
    def _existing_file_inventory(roots: list[str], limit: int=80) -> str:
        """Return only files proven to exist, so agents do not probe guessed artifact paths."""
        discovered: list[Path] = []
        for raw_root in roots:
            root = Path(raw_root)
            if root.is_file():
                discovered.append(root.resolve())
                continue
            if not root.is_dir():
                continue
            for path in sorted(root.rglob('*')):
                if path.is_file():
                    discovered.append(path.resolve())
                    if len(discovered) >= limit:
                        break
            if len(discovered) >= limit:
                break
        if not discovered:
            return '- (none)'
        return '\n'.join((f'- {path}' for path in discovered))

    def _build_node_input(self, node: WorkflowNode, direction: str, run: 'WorkflowRun') -> str:
        """根据节点类型构建差异化的输入消息
    
            每个节点有不同的输入需求：
            - lit: 研究方向 + 关键词
            - idea: 文献综述结果
            - novelty: idea 列表
            - exp-design: 选定的 idea + 文献
            - exp-run: 实验设计方案
            - results: 实验日志/输出
            - figure: 实验结果数据
            - paper: 所有前序输出
            - review: 论文全文
            - audit: 论文 + 实验证据
            - compile: 项目路径
            - ppt: 论文内容摘要
            """
        predecessors = {}
        for n in run.nodes:
            if n.id in node.depends_on and n.output:
                predecessors[n.id] = n.output
        templates = {'lit': self._input_lit, 'idea': self._input_idea, 'novelty': self._input_novelty, 'exp-design': self._input_exp_design, 'exp-run': self._input_exp_run, 'results': self._input_results, 'figure': self._input_figure, 'narrative': self._input_narrative, 'paper': self._input_paper, 'review': self._input_review, 'audit': self._input_audit, 'compile': self._input_compile, 'ppt': self._input_ppt}
        builder = templates.get(node.id)
        if builder:
            message = builder(direction, predecessors, run)
        else:
            message = f'{node.skill} {direction}'.strip()
        if node.id in {'exp-run', 'paper', 'review'}:
            from ..services.protocol_conformance import protocol_readiness_prompt
            message += protocol_readiness_prompt(run.project_path)
        if str(run.options.get('research_mode') or 'from_scratch') == 'paper_code_innovation':
            from .research_mode import build_innovation_node_input
            message += '\n\n' + build_innovation_node_input(node.id, run.project_path)
        if node.id in {'paper', 'review', 'audit', 'compile', 'ppt'}:
            from ..services.paper_budget import paper_budget_service
            budget_prompt = paper_budget_service.prompt(paper_budget_service.normalize(run.options.get('target_pages', 0), run.options.get('target_page_tolerance', 1), str(run.options.get('target_venue') or '')))
            if budget_prompt:
                message += '\n\n' + budget_prompt
        from ..services.workflow_user_constraints import render_user_constraints
        message += render_user_constraints(run.options)
        from ..services.research_edit_context import research_edit_context
        message += research_edit_context(run.project_path, node.id)
        if not (run.checkpoint_node_id == node.id and run.checkpoint_feedback):
            from .operator_feedback import operator_feedback_context
            message += operator_feedback_context(run, node.id)
        return message

    def _input_lit(self, direction: str, preds: dict, run: 'WorkflowRun') -> str:
        from ..services.paper_profile import paper_profile_service
        from ..services.project_scaffold import get_convention_paths
        paths = get_convention_paths(run.project_path)
        strategy = self._normalize_research_strategy(run.options.get('research_strategy', {}))
        survey_paper_limit = max(5, min(80, int(strategy.get('literature_max_papers', 35) or 35)))
        minimum_bibliography = paper_profile_service.bibliography_requirement(run.project_path, options={**dict(run.options or {}), 'research_direction': direction}, direction=direction)
        retrieval_target = max(survey_paper_limit, minimum_bibliography)
        target_words = 1200 if survey_paper_limit <= 12 else 2000 if survey_paper_limit <= 25 else 3200
        research_brief = ''
        brief_path = Path(paths['research_brief'])
        if brief_path.is_file():
            research_brief = brief_path.read_text(encoding='utf-8', errors='replace')[:4000]
        from ..services.knowledge_context import selected_personal_context
        personal_context = selected_personal_context(
            Path(paths['literature']), run.options, strategy.get('literature_sources', [])
        )
        configured_sources = {str(item).strip().casefold() for item in strategy.get('literature_sources', []) if str(item).strip()}
        source_tools = []
        if 'arxiv' in configured_sources:
            source_tools.append('- `arxiv_search` — arXiv 预印本（已启用，必须实际调用）')
        if 'semantic_scholar' in configured_sources:
            source_tools.append('- `semantic_scholar_search` — 引用和元数据检索（已启用，必须实际调用）')
        if 'web' in configured_sources:
            source_tools.append('- `WebSearch` — 出版页、项目页和补充核验（已启用，必须实际调用）')
        if 'gemini' in configured_sources:
            source_tools.append('- `mcp__gemini-cli__search` — 搜索增强（已启用且可用时调用）')
        if not source_tools:
            source_tools = ['- `arxiv_search` — 主题与方法检索', '- `semantic_scholar_search` — 元数据和引用核验']
        source_tool_contract = '\n'.join(source_tools)
        survey_write_example = json.dumps({'path': paths['literature_survey'], 'content': '# Literature Survey\n...完整综述正文...'}, ensure_ascii=False)
        bib_write_example = json.dumps({'path': paths['literature_bib'], 'content': '@article{key,...}\n...'}, ensure_ascii=False)
        return f"请对以下研究方向进行系统性文献调研：\n\n## 研究方向\n{direction}\n\n## 项目研究简报（脚手架与工作流共用）\n{(research_brief if research_brief else '(未填写；按研究方向继续)')}\n\n## 已验证并确定性读取的个人知识源\n{(personal_context if personal_context else '(本轮未选择 Zotero/Obsidian，或未返回记录)')}\n\n个人知识源只用于补充检索词、作者已知工作和内部背景；Obsidian 笔记不是独立科学证据，Zotero 条目仍需核验元数据后才能进入正式引用。\n\n## 输出路径（使用 Write 工具写入以下文件）\n- 文献综述: {paths['literature_survey']}\n- BibTeX 引用: {paths['literature_bib']}\n\n## 执行策略（重要！）\n1. **按用户启用项进行多源搜索**，单次 `max_results` 不超过 8：\n{source_tool_contract}\n   对每个已启用来源至少完成一次成功调用；不要用 WebSearch 冒充已启用的学术来源。\n2. **不要把写文件拖到很晚**：首次生成时，拿到第一批可用论文后，先用 Write 写入 references.bib，再写入一版 compact survey.md。若文件已经存在且本轮是门禁定向修订，优先用 Edit 做最小修改；不得为了满足输出契约再次整文件改写。\n3. 对进入核心比较表的论文做标题、作者、年份和链接一致性检查；其余候选可留给 citation-audit，但不得凭记忆补全元数据。\n4. **必须使用 Write/Edit 工具写入文件，不要用 Bash 命令**。首次生成必须至少 Write 一次；定向修订已经通过 Edit 改变规范产物后，不得再用 Write 重写同一文件。\n5. 搜索关键词策略：先搜主题方向，再搜具体方法名/模型名/数据集名。\n6. 详细综述最多纳入 {survey_paper_limit} 篇核心论文；最终论文画像要求 references.bib 至少包含 {minimum_bibliography} 条经过元数据核验且与正文相关的记录，因此本轮应检索并去重至少 {retrieval_target} 条候选。综述目标约 {target_words} English words（中文按等价信息量）。首批达到 8--12 条时先持久化，再按主题、最近邻方法、数据集/基准和关键机制分批补足。\n\n## 必须调用的工具参数形状\n调用 `Write` 时必须传完整 JSON 参数，不能传空对象：\n```json\n{survey_write_example}\n```\n```json\n{bib_write_example}\n```\n\n## 输出要求\n- survey.md：包含 Search Protocol、纳入/排除规则、主题分类、关键论文对比表、互相矛盾的证据、最近邻方法、证据缺口，以及可检验的下一步假设\n- survey.md 中引用 references.bib 时统一使用 Pandoc Markdown 形式 `[@bibkey]`（多篇用 `[@key1; @key2]`），不要只把 BibTeX key 放在反引号中\n- references.bib：至少 {minimum_bibliography} 条可追溯且可在论文中实际使用的 BibTeX；检索候选目标 {retrieval_target} 条，核心论文必须具备可核查 URL/DOI/arXiv/ISBN 标识，禁止为了凑数保留无关文献\n- 若项目中已存在 `ideas/ideas.md`、`ideas/novelty_report.md` 或 `paper/**/*.tex`，重写 references.bib 前先读取其中的引用键。保留仍被这些下游产物使用且元数据可核验的既有 BibTeX 条目；不得因本轮补充文献而删除它们。发现疑似错误键时做定点修复或明确报告，不能用缩减整个文献库的方式处理。\n- 禁止只罗列论文摘要；每一类工作都要回答其假设、数据范围、证据强度、局限以及与本项目的关系"

    def _input_idea(self, direction: str, preds: dict, run: 'WorkflowRun') -> str:
        from ..services.project_scaffold import get_convention_paths
        paths = get_convention_paths(run.project_path)
        lit_output = preds.get('lit', '')
        if not lit_output:
            try:
                survey = Path(paths['literature_survey'])
                if survey.exists():
                    lit_output = survey.read_text(encoding='utf-8')[:3000]
            except Exception:
                pass
        idea_write_example = json.dumps({'path': paths['ideas_md'], 'content': '# Research Ideas\n...完整 idea 列表正文...'}, ensure_ascii=False)
        return f"基于文献调研结果，生成研究 idea：\n\n## 研究方向\n{direction}\n\n## 文献调研结果\n{(lit_output[:3000] if lit_output else '请先读取 ' + paths['literature_survey'])}\n\n## 输出路径\n- Idea 列表写入: {paths['ideas_md']}\n\n## 必须调用的工具参数形状\n调用 `Write` 时必须传完整 JSON 参数，不能传空对象：\n```json\n{idea_write_example}\n```\n\n## 科研深度要求\n1. 生成多个差异化候选，但每个候选必须包含：Problem Anchor、Falsifiable Hypothesis、Mechanism、Nearest-work Delta、Anti-claims、Failure/Pivot Criteria、Data/Compute Feasibility。\n2. 把“增加一个模块”与“解释一个可检验现象”区分开；没有机制和证伪路径的候选降级或淘汰。\n3. 为每个候选给出最小可信证据、强 baseline、公平性控制、主要失败风险和预期负结果。\n4. 用统一量表排序：科学重要性、真实新颖性、可证伪性、证据可获得性、工程风险；给出分项分数而非只给总排名。\n5. 明确选出 top-1 与备选，并说明什么新证据会触发改选。\n6. **立即使用 Write 工具写入 {paths['ideas_md']}，Write 参数必须包含 path 和 content**；不要用 Bash 写文件。\n7. 不要重复大范围检索；若某个最近邻结论缺证据，标记为待 novelty 节点验证，不能写成已确认事实。"

    def _input_novelty(self, direction: str, preds: dict, run: 'WorkflowRun') -> str:
        from ..services.project_scaffold import get_convention_paths
        paths = get_convention_paths(run.project_path)
        idea_output = preds.get('idea', '')
        if not idea_output:
            try:
                f = Path(paths['ideas_md'])
                if f.exists():
                    idea_output = f.read_text(encoding='utf-8')[:3000]
            except Exception:
                pass
        selected_contract_example = json.dumps({'schema': 2, 'status': 'accepted', 'title': 'Exact accepted Top-1 title', 'problem_statement': 'Research problem grounded in the novelty review', 'hypothesis': 'A falsifiable hypothesis', 'claims': [{'id': 'C1', 'statement': 'Internal measurable claim', 'publication_statement': 'Concise manuscript-facing claim'}], 'mechanisms': [{'id': 'M1', 'name': 'Internal mechanism name', 'description': 'Internal causal or computational role', 'publication_name': 'Concise public mechanism name', 'publication_description': 'One manuscript-facing scientific sentence', 'publication_evaluation': 'Named decisive comparison and endpoint', 'required': True}], 'falsification_conditions': ['Observation that would refute or redirect the idea'], 'publication': {'language': 'en', 'title': 'Publication-facing title', 'method_name': 'Stable method or study name', 'contribution_type': 'objective_mechanism', 'comparator_names': ['Named proposed condition', 'Named matched control']}}, ensure_ascii=False, indent=2)
        selected_contract_write = json.dumps({'path': paths['selected_idea_contract'], 'content': selected_contract_example}, ensure_ascii=False)
        return f"对 idea 进行新颖性检查：\n\n## Idea 列表\n{(idea_output[:3000] if idea_output else '请先读取 ' + paths['ideas_md'])}\n\n## 输出路径\n- 新颖性报告写入: {paths['novelty_report']}\n- 已选 Idea 契约写入: {paths['selected_idea_contract']}\n\n## 科研深度要求\n1. 对 top 候选分别执行 claim-level 最近邻检索；使用 `arxiv_search` + `semantic_scholar_search`，必要时用 `WebSearch` 补充。\n2. 对每个最近邻记录可追溯标识、其真实 claim、数据/协议，以及与候选在问题、机制和证据上的重叠。\n3. 输出 Novelty Delta Matrix：相同点、真正新增点、仅工程变化、尚未验证的差异。\n4. 判断 HIGH / MEDIUM / LOW / DUPLICATE，并单列 novelty risk、prior-art uncertainty 和可能导致拒稿的最近邻。\n5. 推荐 top-1 和备选，不再只给 top-3 列表；给出选择、淘汰与改选条件。\n6. 用 Write 工具写入 ideas/novelty_report.md；没有检索证据时必须写 UNKNOWN，不得凭模型记忆判 HIGH。\n7. 同时写入 `ideas/SELECTED_IDEA.json`，把验收后的 title、claims、mechanisms 和 falsification_conditions\n   固定成后续实验设计不可重定义的结构化契约。\n\n`ideas/SELECTED_IDEA.json` schema example:\n```json\n{selected_contract_example}\n```\n调用方式：`Write({selected_contract_write})`"

    def _input_exp_design(self, direction: str, preds: dict, run: 'WorkflowRun') -> str:
        from ..services.experiment_implementation_build import experiment_implementation_build_service
        from ..services.project_scaffold import get_convention_paths
        paths = get_convention_paths(run.project_path)
        context = preds.get('novelty', '') or preds.get('idea', '')
        if not context:
            try:
                f = Path(paths['novelty_report'])
                if f.exists():
                    context = f.read_text(encoding='utf-8')[:2000]
            except Exception:
                pass
        canonical_context = []
        for candidate in (Path(paths['selected_idea_contract']), Path(paths['novelty_report']), Path(paths['ideas_md'])):
            if candidate.is_file():
                canonical_context.append(candidate.read_text(encoding='utf-8', errors='replace')[:6000])
        if canonical_context:
            context = '\n\n'.join(canonical_context) + '\n\n' + context
        selected_idea = self._extract_selected_idea(Path(run.project_path), context, direction)
        from ..services.method_contract import method_contract_service
        selected_contract_ready, _, _ = method_contract_service.validate_selected_idea(run.project_path, selected_idea)
        if not selected_contract_ready:
            raise ValueError(
                "ideas/SELECTED_IDEA.json is missing or invalid; repair the novelty owner before experiment design"
            )
        blueprint = experiment_implementation_build_service.ensure_blueprint(run.project_path, direction)
        implementation_family = str(blueprint.get('implementation_family') or 'computational_general').strip().casefold()
        entrypoint = str(blueprint.get('entrypoint') or 'experiments/src/run_analysis.py').strip()
        stages = [dict(item) for item in blueprint.get('stages') or [] if isinstance(item, dict)]
        stage_sequence = ' → '.join((str(item.get('title') or item.get('id') or 'stage') for item in stages))
        stage_id_sequence = ' → '.join(('execution' if str(item.get('id') or '') == 'training' and implementation_family != 'machine_learning' else str(item.get('id') or 'stage') for item in stages))
        stage_targets = [{'id': str(item.get('id') or ''), 'title': str(item.get('title') or ''), 'purpose': str(item.get('purpose') or ''), 'targets': list(item.get('targets') or [])} for item in stages]
        family_contracts = {'machine_learning': {'implementation_level': 'executable_training_pipeline', 'execution_paths': {'entrypoint': entrypoint, 'data_path': ['load configured data', 'construct isolated splits', 'create batches'], 'method_path': ['instantiate model', 'forward', 'accepted mechanisms and objectives'], 'execution_path': ['loss', 'backward', 'optimizer step', 'checkpoint selection'], 'evaluation_path': ['task-head inference', 'registered metrics', 'per-unit predictions'], 'persistence_path': ['checkpoint', 'metrics', 'run and provenance ledger']}, 'design_requirements': 'Declare analysis-unit-safe splits, preprocessing fit boundaries, task-head/output paths, matched training controls, mechanism-isolating interventions, optimization budgets, seeds, uncertainty, calibration where applicable, and resource accounting.', 'config_yaml': 'data:\n  manifest: data/manifest.csv\n  analysis_unit: subject_id\n  split_policy: group_disjoint\nmethod:\n  accepted_mechanisms: [M1]\nexecution:\n  seeds: [13, 42, 73]\n  device: auto\nevaluation:\n  primary_outcomes: [claim_specific_primary_metric]\n  controls: [strong_reference, matched_control]\n  mechanism_tests: [remove_M1]\n'}, 'formal_verification': {'implementation_level': 'executable_formal_verification', 'execution_paths': {'entrypoint': entrypoint, 'definition_path': ['formal domain', 'assumptions', 'admissible instances'], 'method_path': ['lemmas', 'construction', 'proof obligations', 'checker'], 'execution_path': ['bounded verification', 'boundary cases', 'counterexample search'], 'evaluation_path': ['verified statements', 'bounds', 'complexity', 'negative cases'], 'persistence_path': ['checker result', 'counterexamples', 'proof provenance ledger']}, 'design_requirements': 'Freeze definitions and assumptions, map every theorem claim to proof obligations, specify boundary instances and counterexample search, compare relevant constructions or bounds, and record checker/build identities and proof-complexity limits.', 'config_yaml': 'formal_domain:\n  assumptions: [A1]\n  instance_registry: experiments/instances/manifest.json\nverification:\n  obligations: [C1]\n  boundary_cases: []\n  counterexample_search: bounded\nevaluation:\n  outcomes: [verified_status, bound, complexity]\n'}, 'external_protocol': {'implementation_level': 'executable_protocol_analysis', 'execution_paths': {'entrypoint': entrypoint, 'population_path': ['eligibility', 'sampling or recruitment', 'analysis units', 'quality control'], 'method_path': ['estimands or coding framework', 'adjustment or adjudication', 'controls'], 'execution_path': ['protocol validation', 'analysis or coding driver', 'missing-data handling'], 'evaluation_path': ['effects or themes', 'uncertainty', 'subgroups or negative cases', 'sensitivity'], 'persistence_path': ['study/corpus identity', 'analysis ledger', 'adjudication and provenance']}, 'design_requirements': 'Declare population/corpus and sampling, eligibility, independent analysis units, estimands or coding rules, confounding/bias controls, missingness, subgroup or negative-case analysis, triangulation/adjudication where applicable, and protocol or registry provenance.', 'config_yaml': 'protocol:\n  population_or_corpus: declared_source\n  analysis_unit: declared_unit\n  eligibility_rules: []\nanalysis:\n  primary_estimands_or_themes: [claim_specific_outcome]\n  controls: [reference_condition]\n  sensitivity_checks: []\nprovenance:\n  protocol_or_corpus_version: required\n'}, 'computational_general': {'implementation_level': 'executable_scientific_analysis', 'execution_paths': {'entrypoint': entrypoint, 'input_path': ['configured inputs', 'parameters', 'analysis units or scenarios'], 'method_path': ['accepted mechanisms', 'algorithm or numerical method', 'reference conditions'], 'execution_path': ['deterministic orchestration', 'failure handling', 'bounded simulation or analysis'], 'evaluation_path': ['registered estimands or metrics', 'sensitivity', 'numerical stability', 'uncertainty'], 'persistence_path': ['results', 'configuration hash', 'run and provenance ledger']}, 'design_requirements': 'Declare inputs, parameters and admissible ranges, analysis units/scenarios, reference conditions, mechanism-necessity tests, numerical stability and sensitivity checks, uncertainty, deterministic configuration, runtime limits, and provenance.', 'config_yaml': 'inputs:\n  manifest: data/manifest.json\n  analysis_unit: declared_unit\nmethod:\n  accepted_mechanisms: [M1]\nexecution:\n  parameter_grid: {}\n  deterministic_seed: 42\nevaluation:\n  primary_outcomes: [claim_specific_outcome]\n  reference_conditions: [strong_reference]\n  sensitivity_checks: []\n'}}
        family_contract = family_contracts.get(implementation_family, family_contracts['computational_general'])
        config_example = json.dumps({'path': str(Path(paths['experiments_configs']) / 'main.yaml'), 'content': f'project:\n  name: merak_research\nimplementation_family: {implementation_family}\nentrypoint: {entrypoint}\n' + str(family_contract['config_yaml'])}, ensure_ascii=False)
        plan_example = json.dumps({'path': str(Path(paths['experiments']) / 'EXPERIMENT_PLAN.md'), 'content': '# Experiment Plan\n...'}, ensure_ascii=False)
        method_contract_example = json.dumps({'schema': 2, 'status': 'implementation_in_progress', 'implementation_level': family_contract['implementation_level'], 'selected_idea': selected_idea, 'idea_contract_path': 'ideas/SELECTED_IDEA.json', 'idea_contract_sha256': '', 'implementation_family': implementation_family, 'execution_paths': family_contract['execution_paths'], 'mechanism_coverage': [{'idea_mechanism_id': 'M1', 'implementation_check_ids': [], 'status': 'staged_pending'}], 'claim_evidence_plan': [{'idea_claim_id': 'C1', 'outcomes': ['Primary measurable outcome'], 'failure_conditions': ['Result that refutes or redirects C1']}], 'implementation_checks': [], 'evaluation_contract': {'primary_outcomes': ['Primary outcome'], 'comparators_or_controls': ['Domain-valid reference or control'], 'component_tests': ['Mechanism-necessity or sensitivity test'], 'failure_conditions': ['Project-level stop or pivot criterion']}}, ensure_ascii=False, indent=2)
        method_contract_example, method_contract_write = method_scene_authoring_example(method_contract_example, paths['method_contract'])
        method_status = str(json.loads(method_contract_example).get('status') or '')
        implementation_blueprint_example = json.dumps({'schema': 1, 'status': 'frozen_for_implementation', 'title': selected_idea, 'implementation_family': implementation_family, 'research_family': blueprint.get('research_family'), 'study_archetype': blueprint.get('study_archetype'), 'entrypoint': entrypoint, 'mechanisms': [{'id': 'M1', 'name': 'Frozen mechanism', 'required': True}], 'claims': [{'id': 'C1', 'statement': 'Frozen measurable claim'}], 'stages': stage_targets, 'integration_contract': blueprint.get('integration_contract') or {}}, ensure_ascii=False, indent=2)
        implementation_blueprint_write = json.dumps({'path': str(Path(paths['experiments']) / 'IMPLEMENTATION_BLUEPRINT.json'), 'content': implementation_blueprint_example}, ensure_ascii=False)
        return f"为选定的研究 idea 冻结实验设计与分阶段实现蓝图：\n\n## 研究方向\n{direction}\n\n## 候选 Idea / 新颖性上下文\n{(context[:3000] if context else '请先读取 ' + paths['novelty_report'])}\n\n## 绑定的 Top-1 Idea（实验方法必须实现，不得换成更容易的通用模型）\n{selected_idea}\n## 强制决策规则\n- 如果上下文里出现多个候选 idea，**不要询问用户选择哪个**。\n- 上面的绑定 Top-1 与 `ideas/SELECTED_IDEA.json` 是已验收上游决策。不得把它替换成任何\n  未在该契约中声明的便捷方案；实现必须逐项覆盖契约里的 required mechanisms。\n- 自动选择 novelty report / ideas.md 中排名最高、推荐最高或最靠前的 idea，并在实验计划中写明 `Auto-selected idea`。\n- 如果信息不足，基于研究方向选择最可执行的 top-1 假设继续推进；不要暂停、不要反问、不要等待人工确认。\n- 本节点必须产出文件；只给解释、建议或问题会被 gate 判失败。\n\n## 输出路径（必须使用 Write 工具）\n- 实验计划: {paths['experiments']}/EXPERIMENT_PLAN.md\n- 运行契约: {paths['experiments']}/RUN_SPEC.json\n- Idea 到实现的追踪契约: {paths['method_contract']}\n- 实验配置: {paths['experiments_configs']}/main.yaml\n- 分阶段实现蓝图: {paths['experiments']}/IMPLEMENTATION_BLUEPRINT.json\n\n## 当前会话职责边界\n- 当前主会话只冻结科学设计、配置、方法/运行契约和实现蓝图，不生成 `experiments/src/` 源代码。\n- 已判定 implementation family：`{implementation_family}`；正式入口：`{entrypoint}`。\n- 返回后平台将启动相互隔离的实现阶段：{stage_id_sequence}（{stage_sequence}）。\n- 每个阶段只拥有自己的目标文件，并在确定性验收通过后才进入下一阶段。\n- `METHOD_CONTRACT.status` 是运行时字段；保留当前值 `{method_status}`（不存在时不要添加）。只有平台在 integration 完整验收后更新状态，模型只能提交科学设计和实现证据。\n\n调用 `Write` 时必须传完整 JSON 参数，不能传空对象。示例：\nWrite({plan_example})\nWrite({config_example})\nWrite({implementation_blueprint_write})\n\n## 科研深度要求\n1. 写明 Auto-selected idea、选择依据、Problem Anchor、核心 claim、anti-claims、机制假设和明确证伪条件。\n2. 建立 Claim-to-Evidence Matrix：每个 claim 对应输入/资料、领域有效的 comparator/control、机制必要性或敏感性检验、主要 outcome、分析方法、成功阈值、失败解释和产物路径。\n3. `{implementation_family}` 专属设计合同：{family_contract['design_requirements']}\n4. 任何 reference/control 必须共享适用的数据、样本、实例、假设、资源或机会预算；如果无法匹配，要预先声明差异及其可解释边界。\n5. 统计或验证计划必须匹配独立分析单位与研究范式；需要推断时写明效应量/区间/多重比较，需要形式验证时写明义务/边界/反例，需要定性分析时写明饱和度/三角互证/负例。\n6. 给出 preflight -> pilot/feasibility -> decisive analysis -> robustness/negative-case 的运行顺序、停止/转向规则、资源预算和预期失败模式。\n7. 生成 YAML 配置到 experiments/configs/main.yaml，并将上述关键协议编码为显式字段，而不是只留在 prose。\n8. 在 `IMPLEMENTATION_BLUEPRINT.json` 中逐项冻结当前 family 的阶段职责、目标文件、接口、数据/形式对象契约和验收条件；不要改回 ML 模板。\n9. `METHOD_CONTRACT.json` 只使用冻结 Idea 中已有的 mechanism/claim ID；当前阶段记录 evidence plan 和 staged_pending 映射，不得虚构尚未生成的代码 symbol。\n10. 规划的最终执行链必须完整覆盖蓝图 `integration_contract.required_flow`，并让全部 required mechanisms 从正式入口可达；不得用只定义未调用的 helper 充当实现。\n11. 只有 `machine_learning` 预测任务才强制声明 task head/logits/probabilities；其他 family 必须声明其对应的 estimand/theme/proof obligation/algorithm output 路径。\n12. `RUN_SPEC.json` 分别声明正式 `command`、可选 `preflight_command` 和项目内 `entrypoint`；正式命令不得携带 `--dry-run`。\n13. “本轮不执行”只限制运行，不降低后续实现深度；完整仿真模式同样需要五阶段代码实现全部通过。\n\n`experiments/METHOD_CONTRACT.json` schema example:\n```json\n{method_contract_example}\n```\n调用方式：`Write({method_contract_write})`"

    def _input_exp_run(self, direction: str, preds: dict, run: 'WorkflowRun') -> str:
        from ..services.project_scaffold import get_convention_paths
        paths = get_convention_paths(run.project_path)
        design = preds.get('exp-design', '')
        return f"根据实验设计，部署并执行实验：\n\n## 实验设计\n{(design[:3000] if design else '请读取 ' + paths['experiments_configs'] + ' 中的配置')}\n\n## 路径约定\n- 代码目录: {paths['experiments_src']}\n- 配置目录: {paths['experiments_configs']}\n- 日志输出: {paths['experiments_logs']}\n- 结果输出: {paths['experiments_results']}\n\n## 要求\n1. 执行实验（本地或远程）\n2. 日志保存到 experiments/logs/\n3. 结果保存到 experiments/results/"

    def _input_results(self, direction: str, preds: dict, run: 'WorkflowRun') -> str:
        from ..services.project_scaffold import get_convention_paths
        from ..services.results_execution_policy import BENCHMARK_RESULTS_RUNTIME, PLANNED_RESULTS_RUNTIME, resolve_results_execution_policy
        policy = resolve_results_execution_policy(run.options)
        if policy.issues:
            raise ValueError('Results execution contract is blocked: ' + '; '.join(policy.issues))
        paths = get_convention_paths(run.project_path)
        inventory = self._existing_file_inventory([paths['experiments_results'], paths['experiments_logs']])
        analysis_policy = '- 对 SIMULATION_MANIFEST.json 声明且哈希有效的 machine-readable metrics 整理 baseline、固定场景、独立分析单位、效应量、不确定性与统计检验。\n- 完整分析主比较、消融、训练动态、鲁棒性、错误分析、校准和效率结果；不得把生成器身份、运行身份或内部证据模式写入面向论文的分析叙事。' if policy.runtime_service == BENCHMARK_RESULTS_RUNTIME else '- 对已执行、导入或二次分析的真实 machine-readable metrics 整理来源、baseline、独立单位、seed、split、效应量与不确定性。\n- 只有存在适用的逐样本或逐 seed 配对数据时才做配对显著性检验。\n- 保留已验证结果及其来源边界；缺失来源或无有效指标应明确报告证据缺口，不得改写成未运行模板、清空已有结果或制造数字。'
        planned_contract = ''
        if policy.runtime_service == BENCHMARK_RESULTS_RUNTIME:
            simulation_root = Path(paths['experiments_results']) / 'simulated'
            planned_contract = f"\n## 完整固定基准结果包\n- 清单: {simulation_root / 'SIMULATION_MANIFEST.json'}\n- 分析输入: {simulation_root}\n\n只分析清单声明且哈希有效的数据、主比较、消融、训练动态、鲁棒性、错误分析、校准和效率资产。按固定基准研究报告定量结论与不确定性；生成器身份、运行身份和内部证据模式只保留在机器侧车，不得写入论文可见内容。\n"
        elif policy.runtime_service == PLANNED_RESULTS_RUNTIME:
            analysis_policy = '- 当前仅有计划证据；明确尚待检验的假设、必要数据与证伪条件，不生成测量结果或统计结论。'
            planned_contract = f"\n## 实验未执行：计划产物的唯一合法路径\n- 清单: {paths['planned_result_manifest']}\n- 使用说明: {paths['planned_result_readme']}\n- 主结果 schema: {paths['planned_main_comparison']}\n- 消融 schema: {paths['planned_ablation']}\n- 鲁棒性 schema: {paths['planned_robustness']}\n- 论文表格模板: {paths['planned_result_tables_tex']}\n\n这些 schema 的测量字段必须保持空白，直到由带溯源的真实运行结果填写。分析报告必须把所有结论标记为 planned/pending，不得进行显著性检验或把模板行写成性能证据。\n"
        elif run.options.get('run_experiment') is not True:
            planned_contract = '\n## 已有或二次分析证据\n本轮不启动训练，但现存的来源可追溯结果仍属于真实分析输入。按冻结的数据、原研究或分析契约解释它们；不得因未启动新实验就把已验证结果降格为 planned/pending。没有有效来源时报告具体证据缺口，不补造实验或数值。\n'
        return f"分析实验结果并生成可审计报告。\n\n## 工作流已发现的现存文件\n{inventory}\n{planned_contract}\n## 读取协议\n1. 只能直接 Read 上述“已发现文件”或“唯一合法路径”中明确列出的文件。\n2. 如果需要其他输入，先对目录调用一次 Glob，并且只 Read Glob 实际返回的路径。\n3. 禁止猜测并探测这些错误别名：\n   - {paths['experiments_results']}/README.md\n   - {paths['experiments_results']}/PLANNED_RESULT_MANIFEST.json\n   - {paths['experiments_results']}/main_comparison.csv\n   - {paths['experiments_results']}/ablation.csv\n   - {paths['experiments_results']}/robustness_sensitivity.csv\n   - {paths['paper']}/planned_result_templates.tex\n4. 缺失文件是证据缺口，应在报告中记录一次，不要对每个预期文件分别调用 Read。\n\n## 输出路径\n- 分析报告: {paths['experiments_results']}/analysis.md\n\n## 分析要求\n{analysis_policy}\n- 使用 Write 工具写入唯一输出路径。"
    def _input_figure(self, direction: str, preds: dict, run: 'WorkflowRun') -> str:
        from ..services.project_scaffold import get_convention_paths
        from ..services.scientific_assets import scientific_asset_service
        from ..services.scientific_figure_prompt import figure_authoring_prompt
        paths = get_convention_paths(run.project_path)
        try:
            asset_plan = scientific_asset_service.build_plan(run.project_path, experiment_requested=run.options.get('run_experiment') is True, requested_evidence_mode=str(run.options.get('non_experiment_evidence_mode') or ''), illustration_mode='auto', direction=direction, target_venue=str(run.options.get('target_venue') or ''), research_family=str(run.options.get('research_family') or ''), study_archetype=str(run.options.get('study_archetype') or ''))
        except ValueError as error:
            return f"Figure stage blocked by upstream scientific asset contract; repair the declared owner before generating figures.\nFinding: {error}"
        persist_figure_specs(run.project_path, asset_plan)
        sources = [paths['selected_idea_contract'], paths['experiments_src'],
                   paths['experiments_configs'], paths['experiments_results'],
                   str(Path(run.project_path) / 'experiments/METHOD_CONTRACT.json'),
                   str(Path(run.project_path) / 'paper/PAPER_PLAN.md'),
                   str(Path(run.project_path) / 'figures/SCIENTIFIC_ASSET_PLAN.json'),
                   str(Path(run.project_path) / 'figures/FIGURE_SPECS.json')]
        inventory = self._existing_file_inventory(sources, limit=120)
        from ..services.figure_preflight import append_figure_preflight_prompt
        return append_figure_preflight_prompt(figure_authoring_prompt(run.project_path, direction, asset_plan, inventory), asset_plan)

    def _input_narrative(self, direction: str, preds: dict, run: 'WorkflowRun') -> str:
        from ..services.narrative_prompt import narrative_authoring_prompt
        from ..services.project_scaffold import get_convention_paths
        paths = get_convention_paths(run.project_path)
        return narrative_authoring_prompt(project_path=run.project_path, direction=direction, options=run.options, paths=paths, inventory_builder=self._existing_file_inventory)

    def _input_paper(self, direction: str, preds: dict, run: 'WorkflowRun') -> str:
        from ..services.figure_artifacts import figure_artifact_registry
        from ..services.paper_artifacts import paper_artifact_builder
        from ..services.project_scaffold import get_convention_paths
        from ..services.scientific_assets import scientific_asset_service
        paths = get_convention_paths(run.project_path)
        figures_root = Path(paths['figures'])
        manifest_path = figure_artifact_registry.manifest_path(figures_root)
        manifest = figure_artifact_registry.reconcile(figures_root) if manifest_path.exists() else figure_artifact_registry.load(figures_root)
        asset_plan = scientific_asset_service.load(run.project_path)
        evidence_mode = str(asset_plan.get('evidence_mode') or 'design_only')
        evidence_boundary_policy = '- This is a complete fixed-benchmark paper track. Analyze the bound quantitative package normally and keep all generator/run provenance exclusively in machine-readable sidecars.\n' if evidence_mode.casefold() == 'synthetic_preview' else '- If experiments have not run, explain the empirical limitation once in scientific prose. Do not turn the abstract, introduction, results, or conclusion into an MERAK execution report.\n'
        result_table_policy = 'add every manifest-bound fixed-benchmark result table required for the main comparison, ablation, robustness, error analysis, calibration, and efficiency discussion.' if evidence_mode.casefold() == 'synthetic_preview' else 'add the runtime-backed main-result table only in executed/existing-results mode.'
        from ..services.paper_preparation_errors import prepare_paper_evidence
        prepare_paper_evidence(run.project_path, direction)
        figure_lines: list[str] = []
        include_examples: list[str] = []
        for item in manifest.get('figures', []):
            if not item.get('paper_ready') or not item.get('output_path'):
                continue
            metadata = dict(item.get('metadata') or {})
            if metadata.get('evidence_status') == 'placeholder':
                continue
            caption = str(item.get('caption') or item.get('description') or 'Research figure')
            paper_path = str(item.get('paper_path') or f"../{item['output_path']}")
            source = item.get('source_path') or 'none'
            figure_lines.append(f"- output={paper_path} | label={metadata.get('label', '')} | role={metadata.get('scientific_role', '')} | evidence={metadata.get('evidence_status', '')} | question={metadata.get('scientific_question', '')} | caption={caption} | editable_source={source}")
            include_examples.append(f'\\\\includegraphics[width=0.95\\\\linewidth]{{{paper_path}}}')
        figures_text = '\n'.join(figure_lines) or '- No valid figure manifest entries found.'
        examples_text = '\n'.join(include_examples[:6]) or '% No valid includegraphics path.'
        input_inventory = self._existing_file_inventory([paths['literature'], paths['ideas'], str(Path(paths['experiments']) / 'EXPERIMENT_PLAN.md'), paths['experiments_configs'], paths['experiments_results'], str(Path(run.project_path) / 'NARRATIVE_REPORT.md'), str(Path(paths['paper']) / 'PAPER_PLAN.md'), str(manifest_path), str(Path(paths['figures']) / 'SCIENTIFIC_ASSET_PLAN.json'), str(Path(paths['figures']) / 'FIGURE_SPECS.json'), paths['paper_tables']])
        return f"Dispatcher metadata for the staged paper writer.\n\nDo not draft, rewrite, or assemble the manuscript from this prompt. The paper\nnode must run `_execute_staged_paper`, which loads the complete paper-write\nskill separately for each bounded section and performs a local review before\nadvancing. If this compatibility input reaches a model directly, return a\nshort routing error and make no file changes.\n\n## Research direction\n{direction}\n\n## Existing inputs discovered before this model call\n{input_inventory}\n\n## Read protocol\n- Read only paths listed above. If another source is needed, call Glob first and Read only a returned path.\n- Do not guess missing aliases. Planned result files live under `experiments/results/templates/` and planned LaTeX tables live under `paper/tables/`.\n- Treat an absent expected artifact as one evidence gap in the paper; do not issue a separate failed Read for every expected filename.\n\n## Verified figure assets\n{figures_text}\n\n## Valid LaTeX include examples\n{examples_text}\n\n## Manuscript and evidence policy\n- Read paper/PAPER_PLAN.md first. It is the executed paper-plan skill artifact and\n  governs section purpose, contribution framing, and figure/table placement.\n- Scientific asset mode: {evidence_mode}. Read SCIENTIFIC_ASSET_PLAN.json before deciding\n  which figures and tables belong in each section.\n- Numerical metrics may appear only when their exact values and provenance exist in real files under\n  experiments/results/ or experiments/logs/.\n- Never invent any quantitative or qualitative observation, verification verdict, metric, effect,\n  interval, sample/corpus/instance count, dataset/cohort identity, theorem status, or reference result.\n- Fixed-benchmark values may only come from the generated deterministic package. Keep generator\n  provenance, internal evidence mode, and run identity exclusively in machine-readable sidecars.\n  Do not expose simulation/synthetic/preview framing, warning banners, watermarks, or internal state\n  in titles, abstracts, scientific sections, figures, tables, or captions. Deterministic assembly owns\n  exactly one disclosure paragraph after the Conclusion and before the bibliography; section writers\n  must not add, move, repeat, or paraphrase it.\n{evidence_boundary_policy.rstrip()}\n- Every scientific claim must trace to a citation, method definition, configuration, or result artifact.\n- `C1`, `M1`, `F1`, gate states, artifact paths, `publication_ready`, claim-to-evidence maps, and workflow\n  status are internal metadata. They must not appear in visible manuscript prose, captions, figures, or tables.\n\n## Structural quality contract used by the staged dispatcher\n1. A completed staged LaTeX document contains at least Introduction, Related Work, Method,\n   Experiments, Results/Discussion, Limitations, and Conclusion.\n2. Include only manuscript-eligible manifest-backed scientific figures from the asset plan.\n   Every figure needs a descriptive caption, its declared fig: label, an in-text \\ref,\n   and a nearby paragraph that explains what comparison or mechanism the reader should infer.\n3. Include at least two substantive \\begin{{table}}...\\end{{table}} environments:\n   use `tables/study_design.tex` and `tables/method_components.tex`; {result_table_policy}\n   Claim maps, execution-status tables,\n   rejection trees, and planning templates are forbidden in the manuscript. Every table needs a caption, a unique tab: label,\n   an in-text reference, and an interpretation in prose.\n4. Use \\cite{{}} with verified keys from references.bib; do not invent citation keys.\n5. Use booktabs and graphicx; keep figure paths exactly as listed above.\n6. Discuss evidence gaps and threats to validity instead of hiding missing results.\n7. Write enough technical detail for a reader to understand the method, input/population/\n   corpus/assumption contract, execution or verification protocol, analysis plan, and current evidence status.\n8. Treat ideas/SELECTED_IDEA.json as frozen: keep the paper title traceable to its title,\n   name every required mechanism in the Method section, and do not replace the accepted\n   mechanism with a simpler unrelated implementation.\n\n## Canonical staged outputs\n- Main paper after deterministic assembly: {paths['paper_main']}\n- Independently reviewed section files: {paths['paper_sections']}\n\nThis dispatcher prompt has no permitted write targets. Do not use Write or\nEdit here; section write targets are supplied only by `_execute_staged_paper`."

    def _input_review(self, direction: str, preds: dict, run: 'WorkflowRun') -> str:
        from ..services.project_scaffold import get_convention_paths
        paths = get_convention_paths(run.project_path)
        return f"对论文进行严格审稿并迭代修改，遵循 auto-review-loop SKILL 的完整流程。\n\n## 论文路径\n{paths['paper_main']}\n\n## 必需的结构化审稿产物\n{run.project_path}/review-stage/REVIEW_STATE.json\n\n## 必需的逐轮 PDF 产物\n- 原稿: {run.project_path}/paper/main_round0_original.pdf\n- 第 N 轮: {run.project_path}/paper/main_roundN.pdf\n- 版式报告与渲染页: {run.project_path}/review-stage/pdf-layout/ 和 pdf-previews/\n\n## 审稿输入\n- 论文: {paths['paper_main']}\n- 冻结 Idea: {run.project_path}/ideas/SELECTED_IDEA.json\n- 方法契约: {run.project_path}/experiments/METHOD_CONTRACT.json\n- 结果分析: {run.project_path}/experiments/results/analysis.md\n- 图表契约: {run.project_path}/figures/SCIENTIFIC_ASSET_PLAN.json\n\n审稿必须逐项检查 claim、机制、证据状态、反例和限制。不能通过只打印分数；\n每轮必须重新编译当前 main.tex，保存编号 PDF，并实际检查 PDF 中的图、表、caption、\n分页、float 位置、裁切/重叠和视觉一致性。每轮必须写入 weaknesses、action_items、\nvisual_review 和修改后的证据边界。\n\n## 方向\n- 论文: {paths['paper_main']}\n- 停止条件: score >= 6 AND verdict ∈ {{ready, almost}}（详见 SKILL）\n- 审稿方向: {direction or '全面审稿，重点关注贡献新颖性、实验充分性、写作清晰度'}"

    def _input_audit(self, direction: str, preds: dict, run: 'WorkflowRun') -> str:
        from ..services.project_scaffold import get_convention_paths
        paths = get_convention_paths(run.project_path)
        return f"执行 5 层科学完整性审计，并追加独立证明审计：\n\n## 审计对象\n- 论文: {paths['paper_main']}\n- 实验代码: {paths['experiments_src']}\n- 实验日志: {paths['experiments_logs']}\n- 实验结果: {paths['experiments_results']}\n- 冻结 Idea: {run.project_path}/ideas/SELECTED_IDEA.json\n- 方法契约: {run.project_path}/experiments/METHOD_CONTRACT.json\n- 审稿状态: {run.project_path}/review-stage/REVIEW_STATE.json\n- 输出: {run.project_path}/audit-results/AUDIT_RESULTS.json\n- 独立证明审计: {run.project_path}/paper/PROOF_AUDIT.json\n\n## 审计 5 层\n1. experiment: 代码是否存在、是否可复现\n2. result-claim: 论文数字是否与日志一致\n3. paper-claim: 论文声明是否有证据支撑\n4. citation: 引用是否真实存在\n5. kill-argument: 是否存在能推翻结论的反证\n\n## 独立证明审计\n6. proof-checker: 若存在 theorem/lemma/proposition/corollary/proof 环境，\n   必须加载并实际执行 `/proof-checker` 独立模型策略；若不存在，必须输出\n   带 no_theorems 探测来源的 NOT_APPLICABLE，不得静默跳过。\n\n使用 `audit_verdict` 工具记录每层结果。每层必须包含 verdict、summary 和实际 inspected evidence；解析失败必须记录为 ERROR，不能当作 PASS。"

    def _input_compile(self, direction: str, preds: dict, run: 'WorkflowRun') -> str:
        from ..services.project_scaffold import get_convention_paths
        paths = get_convention_paths(run.project_path)
        return f"编译 LaTeX 论文为 PDF：\n\n## 路径\n- 项目目录: {paths['paper']}\n- 主文件: {paths['paper_main']}\n- 审计结果: {run.project_path}/audit-results/AUDIT_RESULTS.json\n\n## 要求\n1. 使用 latex_compile 工具编译 paper/main.tex\n2. 如果编译失败，分析错误并修复\n3. 确认 PDF 生成在 paper/main.pdf\n4. 生成或刷新 `paper/PAPER_BUILD.json`，绑定当前 TeX 源文件哈希和 PDF 哈希。\n5. 页数目标是软约束，不得用 filler、重复图表或改变科学内容强行凑页数。"

    def _input_ppt(self, direction: str, preds: dict, run: 'WorkflowRun') -> str:
        from ..services.project_scaffold import get_convention_paths
        paths = get_convention_paths(run.project_path)
        from ..services.slide_presentation_projection import slide_figure_inventory
        inventory = ''
        evidence_mode = 'executed' if run.options.get('run_experiment') is True else str(run.options.get('non_experiment_evidence_mode') or 'design_only').strip().casefold()
        if evidence_mode == 'synthetic_preview':
            from ..services.slide_figures import required_synthetic_figure_ids
            try:
                required_figures = ', '.join(required_synthetic_figure_ids(Path(run.project_path)))
                inventory = slide_figure_inventory(Path(run.project_path))
            except (OSError, UnicodeError, ValueError, KeyError, TypeError) as error:
                return (f'BLOCKED: 演示图集证据缺失、过期或与冻结贡献不一致。\n'
                        f'当前诊断: {type(error).__name__}: {error}\n'
                        f'需由上游所有者提供当前 ideas/SELECTED_IDEA.json、完整七角色 '
                        f'SIMULATION_MANIFEST.json 与哈希有效的源、数据和变体。\n'
                        f'本消息仅说明阻塞，证据尚未通过，不能开始生成或声明演示已验收。\n'
                        f'不启动训练或模型，不生成数字或默认图 ID，不更改 selection 位；'
                        f'修复必须返回原科学产物所有者，PPT 门禁保持阻塞。')
            figure_policy = f'\n4. 当前证据模式是完整的确定性基准研究。保留完整七角色证据包，但演示不机械纳入七图。\n   除普通 paper-selected 方法图外，按冻结贡献与论文相同的图集完整引用以下必需结果图：\n   {required_figures}\n   每个入选条目必须同时满足 evidence_status=synthetic_preview、paper_ready=true、\n   paper_selected=true、manuscript_eligible=true、submission_eligible=false、\n   provenance_kind=deterministic_simulation_preview，且 output、源数据、源与全部变体、\n   SIMULATION_MANIFEST 哈希均有效。未选图保留原文件与未选状态，不得为了凑数更改选择位。\n5. 分析入选贡献图支持的当前基准证据，结论严格限定在已注册场景和生成器假设内；\n   生成记录只能支持描述性排序；如论文明确尚无真实实验或 claim pending，必须保留该边界。\n6. 演示正文、图题和页眉页脚不得出现 preview、NOT FOR SUBMISSION、证据状态标签、\n   警告框或水印；投稿资格只保留在机器侧车。'
        else:
            figure_policy = '\n4. 只引用 FIGURE_MANIFEST 中 paper-selected 的图表，并优先复用论文核心方法图和主结果图。\n5. 保留论文中的 claim maturity，不得把 pending 写成已验证结果。'
            inventory = slide_figure_inventory(Path(run.project_path)) if (Path(run.project_path) / 'figures/FIGURE_MANIFEST.json').exists() else ''
        return f"根据论文制作 Beamer 演示文稿：\n\n## 输入\n- 论文: {paths['paper_main']}\n- 图表: {paths['figures']}\n- 图表清单: {paths['figures']}/FIGURE_MANIFEST.json\n- 图表契约: {paths['figures']}/SCIENTIFIC_ASSET_PLAN.json\n- 当前证据模式: {evidence_mode}\n\n## 当前已验证演示图路径\n只引用下面的当前输出；论文存在 print projection 时，不得换回原始图。\n{inventory}\n\n## 输出\n- Beamer 文件: {paths['slides']}/main.tex\n\n## 要求\n1. 当前是无人值守工作流，AUTO_PROCEED=true；不得请求用户确认或停在内部 checkpoint。\n2. 完整执行已加载的 /paper-talk skill，先从论文提炼 claim-first 大纲，再生成演示源文件。\n3. 读取 paper/main.tex，生成与目标场合匹配的 15-20 页演示，不机械堆叠论文段落。\n{figure_policy}\n7. 写入 slides/SLIDE_OUTLINE.md、slides/main.tex、slides/speaker_notes.md 和 slides/TALK_SCRIPT.md。\n8. 可通过 Skill 调用 /paper-slides 或 /slides-polish，但每个只调用一次，不得递归循环。\n9. 运行时会负责编译与刷新 slides/SLIDE_BUILD.json；模型不得伪造编译成功。\n10. 投影可读性是硬约束：正文和引用不得使用 `\\tiny` 或 `\\scriptsize`；\n   最小使用 `\\footnotesize`，内容放不下时必须拆分 frame，不能缩小字体掩盖过载。"

    def _normalize_research_strategy(self, raw: Optional[dict]) -> dict:
        """Normalize fine-grained research controls from UI/API into one contract."""
        from datetime import datetime
        raw = raw if isinstance(raw, dict) else {}
        current_year = datetime.now().year
    
        def as_int(value, default: int, lo: int, hi: int) -> int:
            try:
                parsed = int(value)
            except (TypeError, ValueError):
                parsed = default
            return max(lo, min(hi, parsed))
        year_from = as_int(raw.get('literature_year_from'), 2021, 1900, current_year)
        year_to = as_int(raw.get('literature_year_to') or current_year, current_year, 1900, current_year)
        if year_to < year_from:
            year_from, year_to = (year_to, year_from)
        sources = raw.get('literature_sources') or ['arxiv', 'semantic_scholar']
        if isinstance(sources, str):
            sources = [item.strip() for item in sources.split(',') if item.strip()]
        allowed_sources = {'arxiv', 'semantic_scholar', 'openalex', 'pubmed', 'web', 'gemini', 'zotero', 'obsidian'}
        sources = [item for item in sources if item in allowed_sources] or ['arxiv', 'semantic_scholar']
        policy = str(raw.get('evidence_policy') or 'recent_balanced')
        if policy not in {'recent_balanced', 'frontier_first', 'classic_balanced', 'systematic'}:
            policy = 'recent_balanced'
        return {'literature_year_from': year_from, 'literature_year_to': year_to, 'literature_max_papers': as_int(raw.get('literature_max_papers'), 35, 5, 80), 'literature_sources': sources, 'literature_venues': str(raw.get('literature_venues') or '').strip(), 'include_keywords': str(raw.get('include_keywords') or '').strip(), 'exclude_keywords': str(raw.get('exclude_keywords') or '').strip(), 'seed_papers': str(raw.get('seed_papers') or '').strip(), 'evidence_policy': policy, 'novelty_window_years': as_int(raw.get('novelty_window_years'), 3, 1, 10)}

    def _save_research_strategy(self, project_path: str, run_id: str, strategy: dict) -> None:
        """Persist the exact research-control contract for audit and resume."""
        path = Path(project_path) / '.merak' / 'research_strategy.json'
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            existing = json.loads(path.read_text(encoding='utf-8-sig'))
        except (OSError, UnicodeError, json.JSONDecodeError):
            existing = {}
        if isinstance(existing, dict) and int(existing.get('schema') or 0) == 1 and (str(existing.get('run_id') or '') == str(run_id)) and (existing.get('strategy') == strategy):
            return
        payload = {'run_id': run_id, 'strategy': strategy, 'schema': 1, 'updated_at': time.time()}
        atomic_write_json(path, payload)

    def _restore_search_strategy_provenance(self, project_path: str, strategy: dict[str, Any]) -> str:
        """Reuse retrieval provenance only when its original strategy is identical."""
        root = Path(project_path)
        evidence_path = root / 'literature' / 'SEARCH_EVIDENCE.json'
        try:
            evidence = json.loads(evidence_path.read_text(encoding='utf-8-sig'))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return ''
        evidence_run_id = str(evidence.get('run_id') or '').strip()
        evidence_sources = {str(item).strip() for item in evidence.get('selected_sources') or [] if str(item).strip()}
        requested_sources = {str(item).strip() for item in strategy.get('literature_sources') or [] if str(item).strip()}
        if not evidence_run_id or evidence_sources != requested_sources:
            return ''
        prior_state_path = root / '.merak' / 'runs' / f'{evidence_run_id}.json'
        try:
            prior_state = json.loads(prior_state_path.read_text(encoding='utf-8-sig'))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return ''
        prior_options = dict(prior_state.get('config', {}).get('options') or {})
        prior_strategy = self._normalize_research_strategy(prior_options.get('research_strategy') or {})
        if prior_strategy != strategy:
            return ''
        self._save_research_strategy(project_path, evidence_run_id, strategy)
        return evidence_run_id

    def _build_research_strategy_prompt(self, strategy: dict, node_id: str) -> str:
        """Render strategy controls as hard workflow constraints for every agent node."""
        policy_labels = {'recent_balanced': 'Recent-balanced: prioritize recent SOTA while keeping a small number of seminal anchors.', 'frontier_first': 'Frontier-first: prefer the newest competitive work; cite classics only when they define the field.', 'classic_balanced': 'Classic-balanced: include seminal foundations plus recent deltas.', 'systematic': 'Systematic: explicitly report inclusion/exclusion criteria, sources, queries, and coverage gaps.'}
        lines = ['## Research Strategy Controls', 'These controls are user-selected and override generic skill defaults.', f"- Literature year window: {strategy['literature_year_from']} to {strategy['literature_year_to']}.", f"- Maximum papers to include in the main survey: {strategy['literature_max_papers']}.", f"- Enabled sources: {', '.join(strategy['literature_sources'])}.", f"- Evidence policy: {policy_labels.get(strategy['evidence_policy'], strategy['evidence_policy'])}", f"- Novelty horizon: treat papers from the last {strategy['novelty_window_years']} year(s) as frontier competitors."]
        if strategy.get('literature_venues'):
            lines.append(f"- Venue/domain filter: {strategy['literature_venues']}.")
        if strategy.get('include_keywords'):
            lines.append(f"- Required topical keywords: {strategy['include_keywords']}.")
        if strategy.get('exclude_keywords'):
            lines.append(f"- Exclusion keywords/topics: {strategy['exclude_keywords']}.")
        if strategy.get('seed_papers'):
            lines.append(f"- Literature seed papers to check first during retrieval and novelty screening: {strategy['seed_papers']}.")
        if node_id == 'lit':
            source_calls = ', '.join((f'{source} -> `{LITERATURE_SOURCE_TOOLS[source]}`' for source in strategy['literature_sources'] if source in LITERATURE_SOURCE_TOOLS))
            lines.extend(['', 'Literature-node requirements:', f'- Required source calls for this run: {source_calls}.', '- Invoke every selected source through its dedicated tool at least once. Do not substitute WebSearch for arXiv or Semantic Scholar.', '- MERAK records tool events in literature/SEARCH_EVIDENCE.json. A source is not considered used merely because it is named in prose.', '- Every search query must respect the year window unless explicitly marked as a seminal exception.', "- Write a 'Search Protocol' section in literature/survey.md with year range, sources, query terms, filters, and exclusion rules.", '- Separate frontier papers from background papers; do not silently mix out-of-window citations into the main evidence table.', '- During a targeted literature revision, edit existing canonical files minimally. Before changing references.bib, preserve every verified key still cited by existing idea, novelty, or paper artifacts; never replace the whole bibliography merely to add or correct a few records.'])
        elif node_id in {'idea', 'novelty'}:
            lines.extend(['', 'Idea/novelty-node requirements:', '- Score ideas against frontier competitors inside the novelty horizon.', '- Mark each idea as NEW / INCREMENTAL / RISKY / DUPLICATED with concrete paper evidence.', "- Preserve the user's research direction; do not optimize for easy experiments if it weakens the core idea."])
            if node_id == 'novelty':
                source_calls = ', '.join((f'{source} -> `{LITERATURE_SOURCE_TOOLS[source]}`' for source in strategy['literature_sources'] if source in LITERATURE_SOURCE_TOOLS))
                lines.extend([f'- Required source calls for novelty screening: {source_calls}.', '- Invoke every selected source through its dedicated tool at least once; do not substitute WebSearch for a selected structured database.', '- MERAK verifies these calls from runtime events in literature/SEARCH_EVIDENCE.json, not from the report wording.'])
        elif node_id in {'exp-design', 'exp-run', 'results'}:
            lines.extend(['', 'Scientific execution-node requirements:', '- Design domain-valid reference conditions and mechanism-necessity/sensitivity checks against the selected evidence policy and frontier competitors.', '- If evidence is missing for a claim, emit a measurable analysis, protocol, verification obligation, or mark the claim as unsupported instead of inventing support.'])
        elif node_id in {'paper', 'review', 'audit'}:
            lines.extend(['', 'Writing/review-node requirements:', '- Claims must be traceable to the filtered literature or project artifacts.', '- Do not broaden the paper beyond the selected search scope without explicitly labeling it as future work or background.'])
        return '\n'.join(lines)

    async def _execute_audit_node(self, node: WorkflowNode, run: WorkflowRun, assurance: str) -> str:
        """Run five scientific audits plus the independent proof-checker gate."""
        from ..services.project_scaffold import get_convention_paths
        from ..services.skill_orchestrator import skill_orchestrator
        skill_plan = skill_orchestrator.select(node.id, node.skill, run.project_path, {**dict(run.options or {}), 'assurance': assurance})
        skill_trace_path = skill_orchestrator.record(run.project_path, run.id, skill_plan)
        await self._emit(run, 'skill_plan_selected', {'node_id': node.id, 'primary': skill_plan.primary, 'specialists': skill_plan.specialists, 'validators': skill_plan.validators, 'registry_total': skill_plan.registry_total, 'trace_path': str(skill_trace_path), 'execution_kind': skill_plan.execution_kind, 'runtime_service': skill_plan.runtime_service, 'policy_required': skill_plan.policy_required})
        skill_orchestrator.mark_execution(run.project_path, run.id, node.id, skill_plan.primary, 'running', role='primary', policy_loaded=True, execution_kind='hybrid')
        operation_id = uuid.uuid4().hex[:12]
        runtime_service = skill_plan.runtime_service or 'five_layer_audit_coordinator'
        skill_orchestrator.mark_runtime_execution(run.project_path, run.id, node.id, runtime_service, 'running', operation_id=operation_id)
        paths = get_convention_paths(run.project_path)
        paper_path = paths.get('paper_main') or str(Path(run.project_path) / 'paper' / 'main.tex')
        experiment_dir = paths.get('experiments') or str(Path(run.project_path) / 'experiments')
    
        async def on_progress(message: str):
            await self._emit(run, 'audit_progress', {'node_id': node.id, 'message': message})
        evidence_mode = 'executed' if run.options.get('run_experiment') is True else str(run.options.get('non_experiment_evidence_mode') or 'design_only')
    
        async def run_audit_once():
            audit_results = await audit_chain.run_full_audit(paper_path=paper_path, experiment_dir=experiment_dir, project_path=run.project_path, on_progress=on_progress, evidence_mode=evidence_mode, layer_timeout_seconds=int(run.options.get('audit_layer_timeout_seconds', 420) or 420), run_id=run.id)
            if evidence_mode in {'executed', 'existing_results', 'secondary_analysis'}:
                transport_failures = [item for item in audit_results if item.verdict == Verdict.ERROR and self._is_transport_research_error(RuntimeError(str(item.summary or '')))]
                if transport_failures:
                    raise RuntimeError('Audit model transport failed: ' + '; '.join((item.summary for item in transport_failures[:3])))
            return audit_results
        try:
            results = await self._execute_with_model_transport_retry(run=run, node_id=node.id, operation_name='audit/five-layer-plus-proof', stage_id='five-layer-plus-proof', operation=run_audit_once, opts=run.options)
        except Exception as exc:
            error = self._exception_summary(exc)
            skill_orchestrator.mark_execution(run.project_path, run.id, node.id, skill_plan.primary, 'failed', role='primary', error=error, policy_loaded=True, execution_kind='hybrid')
            skill_orchestrator.mark_runtime_execution(run.project_path, run.id, node.id, runtime_service, 'failed', operation_id=operation_id, error=error)
            raise
        layer_skills = {1: 'experiment-audit', 2: 'result-to-claim', 3: 'paper-claim-audit', 4: 'citation-audit', 5: 'kill-argument', 6: 'proof-checker'}
        for item in results:
            executed_skill = str(item.skill_name or layer_skills.get(item.layer, ''))
            execution_status = 'completed' if item.method == 'model' and item.policy_loaded else 'completed' if item.method == 'deterministic_detector' and item.verdict == Verdict.NOT_APPLICABLE and item.policy_loaded else 'recovered' if item.method == 'deterministic_fallback' else 'failed'
            skill_orchestrator.mark_execution(run.project_path, run.id, node.id, executed_skill, execution_status, role='primary' if item.layer == 1 else 'validator' if item.layer == 6 else 'audit_layer', session_id=item.session_id, output=item.summary, error='' if execution_status == 'completed' else item.summary, policy_loaded=item.policy_loaded, execution_kind='hybrid', model_name=item.model_name)
            await self._emit(run, 'audit_skill_execution', {'node_id': node.id, 'layer': item.layer, 'skill': executed_skill, 'status': execution_status, 'session_id': item.session_id, 'policy_loaded': item.policy_loaded, 'method': item.method})
        payload = {'assurance': assurance, 'evidence_mode': evidence_mode, 'results': [{'layer': item.layer, 'layer_name': item.layer_name, 'verdict': item.verdict.value, 'summary': item.summary, 'details': item.details, 'evidence': item.evidence, 'method': item.method, 'skill_name': item.skill_name or layer_skills.get(item.layer, ''), 'session_id': item.session_id, 'policy_loaded': item.policy_loaded, 'model_name': item.model_name, 'reason_code': item.reason_code, 'audited_input_hashes': item.audited_input_hashes, 'trace_path': item.trace_path} for item in results]}
        summary = json.dumps(payload, ensure_ascii=False, indent=2)
        skill_orchestrator.mark_runtime_execution(run.project_path, run.id, node.id, runtime_service, 'completed', operation_id=operation_id, output=summary)
        return summary
