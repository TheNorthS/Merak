"""Time-bounded real-model verification through the original 0.1.x workflow request path."""

import argparse
import asyncio
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.verify_research_workflow_live import initialize_providers, verify_runtime
from server.api.workflow import WorkflowRunRequest
from server.api.workflow_run_service import prepare_workflow_run
from server.contracts.workflow_nodes import WORKFLOW_NODES
from server.services.project_scaffold import scaffold_project
from server.services.experiment_runner import experiment_scheduler
from server.utils.atomic_write import atomic_write_json
from server.workflows.engine import WorkflowEngine
from server.workflows.run_state import RunState

CASES = {
    'compute': '''Investigate how sensor noise and missing observations affect short-horizon prediction of
autoregressive sensor time series. Develop and ACTUALLY EXECUTE a reproducible CPU study with independently
generated training/development/test sequences, three seeds, a conventional persistence baseline, a simple
linear predictor and a matched missingness control. Compute metrics from predictions and uncertainty over
independent sequences. No neural training, GPU, downloaded datasets or remote compute. Use standard local
Python numerical libraries, preserve scripts, seeds, predictions and execution logs. Never assign preset
method scores or require the proposed method to win. Literature review depth is 35 relevant papers, with
verified metadata and source-grounded claims. Deliver all 13 selected workflow stages through a complete
reviewable paper, real PDF, editable presentation and presentation PDF. Keep the research question narrow
enough for the budget while preserving all scientific checks. Clearly label the synthetic data and claims.''',
    'design': '''Develop a research proposal on how urban tree canopy configuration affects pedestrian heat
exposure across street geometries and climates. Review 35 primary studies, distinguishing air temperature,
surface temperature and thermal-comfort endpoints and observational, controlled and simulation evidence.
Select and justify a research question, design a falsifiable protocol and an evidence-grounded narrative.
This is design-only: do not run experiments or produce fake quantitative results. Use the original workflow's
applicable non-experiment path, conceptual evidence diagrams and a complete research-proposal manuscript,
independent review, audit, compiled PDF and editable presentation plus PDF. Unknowns remain explicit.''',
    'eeg': '''Self-supervised Representation Learning and Foundation Models for EEG Signals. Complete the
original 35-paper research review, source-grounded comparisons, research question, novelty analysis and
research design. Compare objectives, corpora, montage assumptions, preprocessing, split/leakage controls,
downstream evaluation, limitations and closest work. Data/GPU setup and training were explicitly deferred:
use design_only, never random simulated replacements or claimed measured superiority. Deliver complete
review/protocol manuscript, source-based conceptual figures, independent review, audit, real paper PDF,
editable presentation and presentation PDF. Preserve limitations and all requested stages.''',
}


async def main(args):
    frozen = verify_runtime()
    project = args.project.resolve()
    if not project.is_relative_to(args.settings_root.resolve() / 'output') or project.exists():
        raise ValueError('Use a fresh project inside workspace output')
    scaffold_project(project, name='Release verification ' + args.case, direction=CASES[args.case], mode='create')
    initialize_providers(args.settings_root)
    request = WorkflowRunRequest(project_path=str(project), node_ids=[node['id'] for node in WORKFLOW_NODES],
        research_direction=CASES[args.case], delivery_goal='reviewable_draft', effort='balanced', assurance='draft',
        run_experiment=args.case == 'compute', gpu_target='local' if args.case == 'compute' else 'none',
        non_experiment_evidence_mode='design_only', literature_max_papers=35,
        literature_sources=['arxiv', 'openalex'], target_pages=9, target_page_tolerance=1,
        research_family='engineering_systems' if args.case == 'compute' else 'auto',
        study_archetype='simulation_modeling' if args.case == 'compute' else 'auto',
        experiment_timeout_seconds=900, human_checkpoint=False, auto_proceed=True)
    options = prepare_workflow_run(request).options
    host = WorkflowEngine()
    report = {'accepted': False, 'case': args.case, 'source_id': frozen, 'real_models': True}
    atomic_write_json(project / '.merak/verification-request.json', request.model_dump())

    async def event(kind, data):
        with (project / '.merak/verification-events.jsonl').open('a', encoding='utf8') as stream:
            stream.write(json.dumps({'type': kind, **data}, ensure_ascii=False, default=str) + '\n')

    run_id = await host.execute(node_ids=request.node_ids, project_path=str(project),
        research_direction=request.research_direction, effort=request.effort, assurance=request.assurance,
        pipeline_options=options, on_event=event)
    report['run_id'] = run_id
    atomic_write_json(project / '.merak/verification-active.json', report)
    started, previous = time.monotonic(), None
    task = host._running_tasks[run_id]
    while not task.done():
        state = RunState(str(project), run_id).load() or {}
        brief = {'status': state.get('status'), 'phases': {k: v.get('status') for k, v in state.get('phases', {}).items()}}
        if brief != previous:
            print(json.dumps(brief), flush=True)
            previous = brief
        if time.monotonic() - started > args.max_seconds or (project / '.merak/cancel.request').exists():
            await host.cancel_run(run_id)
            break
        await asyncio.wait({task}, timeout=3)
    if not task.cancelled():
        await task
    state = RunState(str(project), run_id).load() or {}
    phases = {k: v.get('status') for k, v in state.get('phases', {}).items()}
    report.update(status=state.get('status'), phases=phases, unchanged=verify_runtime() == frozen,
                  seconds=time.monotonic() - started, computation_requested=request.run_experiment)
    report['accepted'] = report['status'] == 'completed' and all(phases.get(n) == 'accepted' for n in request.node_ids) and report['unchanged']
    atomic_write_json(project / '.merak/verification-report.json', report)
    print(json.dumps(report), flush=True)
    return 0 if report['accepted'] else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--allow-real-model', action='store_true', required=True)
    parser.add_argument('--settings-root', type=Path, required=True)
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--case', choices=list(CASES), required=True)
    parser.add_argument('--max-seconds', type=int, default=5400)
    sys.stdout.reconfigure(encoding='utf8')
    os.chdir(ROOT)
    async def with_services():
        args = parser.parse_args()
        await experiment_scheduler.start()
        try:
            return await main(args)
        finally:
            await experiment_scheduler.stop()
    raise SystemExit(asyncio.run(with_services()))
