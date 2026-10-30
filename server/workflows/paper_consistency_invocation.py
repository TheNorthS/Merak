"""Independent no-tool consistency review over a complete frozen manuscript packet."""

import asyncio
import hashlib
import json
from pathlib import Path
import time
import uuid

from ..utils.atomic_write import atomic_write_json, atomic_write_text


def consistency_evidence(root: Path) -> list[Path]:
    from ..services.latex_bundle import _reachable_sources
    paths = {path for path in _reachable_sources(root / 'paper/main.tex', root / 'paper', root)
             if path.suffix.casefold() in {'.tex', '.bib'}}
    paths.update((root / 'paper/sections').glob('*.tex'))
    paths.update(root / name for name in ('paper/references.bib', 'paper/PAPER_PLAN.md',
        'paper/CONTRIBUTION_BLUEPRINT.md', 'paper/SECTION_CONTRACTS.json', 'paper/PAPER_PROFILE.json',
        'experiments/METHOD_CONTRACT.json', 'experiments/EXPERIMENT_PLAN.md', 'experiments/results/analysis.md',
        'experiments/RUN_SPEC.json', 'experiments/configs/main.yaml',
        'experiments/results/accepted_matrix.json',
        '.merak/quality/independent-matrix-audit.json',
        'experiments/src/models.py', 'experiments/src/objectives.py', 'NARRATIVE_REPORT.md',
        'paper/WRITING_REFERENCE_GUIDE.md',
        'experiments/results/simulated/reproducibility/replay/REPLAY_VERIFICATION.json',
        'experiments/results/simulated/reproducibility/replay/CONSTRUCTORS.md'))
    return sorted(path for path in paths if path.is_file() and path.stat().st_size)


def consistency_primary_evidence(root: Path) -> list[Path]:
    """Review current claims against primary science, not superseded authoring instructions.

    Planning artifacts remain in the full stage identity. Local stage contracts
    validate their writing requirements; they are not printed scientific claims.
    """
    planning = {'paper/PAPER_PLAN.md', 'paper/CONTRIBUTION_BLUEPRINT.md',
        'paper/SECTION_CONTRACTS.json', 'paper/PAPER_PROFILE.json',
        'paper/WRITING_REFERENCE_GUIDE.md', 'NARRATIVE_REPORT.md'}
    return [path for path in consistency_evidence(root)
            if path.relative_to(root).as_posix() not in planning]


async def invoke_consistency(run, skill: str, on_event) -> str:
    from ..agent.session_models import AgentEvent
    from ..agent.tools.skill_tool import _load_skill
    from ..services.api_visual_reviewer import ApiVisualReviewer
    from ..services.paper_stage_prompts import _consistency_prompt
    from ..services.paper_draft_state import drafting_paths
    from ..services.manuscript_text import read_json
    from ..services.research_delivery_prompt import research_delivery_instruction
    from .consistency_response_contract import SCHEMA, bound_consistency_report

    root = Path(run.project_path).resolve()
    from .paper_method_presentation import refresh_method_presentation
    await refresh_method_presentation(run, on_event)
    loaded = _load_skill(skill, str(root), 'skill-chain:workflow-staged-paper')
    paths = drafting_paths(root)
    contracts, profile = read_json(paths['contracts']), read_json(paths['profile'])
    prompt = (_consistency_prompt(paths, contracts.get('evidence', {}), profile)
        + citation_inventory(root)
        + '\nThe current manuscript, tables, bibliography, primary implementation, experimental contract, '
        'configuration and result analysis are supplied in the frozen packet. Authoring plans, style guides '
        'and intermediate narratives are excluded: their requirements are checked by author-stage contracts; '
        'they are not current printed claims. No tools or file access are available. '
        'Return the complete Markdown report in the report field. Do not request more reading, change source '
        'files or claim visual inspection: this checks source consistency, separate PDF review checks pixels. '
        'Read planned and implemented scope separately; truthful missing experiments are limitations, not contradictions.'
        + '\nLoaded producer policy (bounded to independent consistency only):\n' + loaded.policy
        + research_delivery_instruction(getattr(run, 'options', {}))
        + '\nReturn an explicit verdict field PASS or FAIL consistent with the report. '
          'For a reviewable draft, repeated truthful disclaimers alone are nonblocking editorial advice. '
          'Actual contradictory labels or false scientific statements remain blocking.')
    from ..services.execution_review_evidence import execution_review_summary
    prompt += execution_review_summary(root)
    feedback = str(getattr(run, 'options', {}).get('resume_feedback') or '').strip()
    if feedback:
        prompt += '\nResearcher feedback to verify against current evidence, never an acceptance verdict:\n' + feedback
    started, token = time.time(), uuid.uuid4().hex[:12]
    trace_path = root / '.merak/skill-invocations' / f'{token}_{loaded.name}.json'
    trace = {'schema': 1, 'id': token, 'skill': loaded.name, 'role': 'delegate', 'status': 'running',
        'started_at': started, 'project_path': str(root), 'policy_loaded': True,
        'skill_source': str(loaded.source), 'skill_sha256': hashlib.sha256(loaded.source_bytes).hexdigest(),
        'skill_bytes': len(loaded.source_bytes), 'allowed_tools': [], 'execution_kind': 'hybrid',
        'workflow_run_id': run.id, 'parent_context': 'skill-chain:workflow-staged-paper'}
    atomic_write_json(trace_path, trace)
    async def activity():
        await on_event(AgentEvent(type='step', data={'kind': 'observe', 'title': '独立一致性审查返回内容'}))
    task = asyncio.create_task(ApiVisualReviewer().invoke(project_path=root, prompt=prompt,
        purpose='paper-consistency', schema=SCHEMA, evidence_paths=consistency_primary_evidence(root),
        timeout_seconds=360, on_activity=activity))
    try:
        while not task.done():
            await asyncio.wait({task}, timeout=15)
            if not task.done():
                await on_event(AgentEvent(type='status', data={'status': 'waiting_model',
                    'elapsed': int(time.time() - started), 'transport': 'frozen-consistency-packet'}))
        result = await task
        report = bound_consistency_report(json.loads(result.text))
        atomic_write_text(paths['cross_review'], report)
        from ..services.paper_drafting import paper_drafting_service
        atomic_write_json(root / '.merak/paper-consistency-binding.json', {
            'schema': 1, 'report_sha256': hashlib.sha256(report.encode()).hexdigest(),
            'input_signature': paper_drafting_service.stage_input_signature(paths, 'consistency'),
            'invocation_id': result.invocation_id, 'trace_path': result.trace_path})
        trace.update(status='completed', session_id=result.invocation_id, model_provider=result.provider_name,
            model_name=result.model_identity, native_trace=result.trace_path,
            output_sha256=hashlib.sha256(report.encode()).hexdigest(), finished_at=time.time())
        atomic_write_json(trace_path, trace)
        return report
    except BaseException as error:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        trace.update(status='cancelled' if isinstance(error, asyncio.CancelledError) else 'failed',
            error_type=type(error).__name__, finished_at=time.time())
        atomic_write_json(trace_path, trace)
        raise


def citation_inventory(root: Path) -> str:
    """Counts are mechanical facts; claim support and relevance remain the reviewer's judgment."""
    from ..services.latex_bundle import _reachable_sources
    from ..services.manuscript_text import citation_keys, bib_keys
    from ..services.simulation_policy import strip_latex_comments
    cited = set()
    for path in _reachable_sources(root / 'paper/main.tex', root / 'paper', root):
        if path.suffix == '.tex':
            cited.update(citation_keys(strip_latex_comments(path.read_text(encoding='utf-8-sig'))))
    known = bib_keys(root / 'paper/references.bib')
    return ('\nRuntime-computed citation inventory from the reachable manuscript: '
        + json.dumps({'unique_cited_keys': len(cited), 'known_cited_keys': len(cited & known),
                      'keys': sorted(cited), 'unknown_keys': sorted(cited-known)})
        + '\nDo not estimate cardinality by eye. These counts do not prove relevance or contextual support; '
          'identify specific unsupported claims separately.\n')
