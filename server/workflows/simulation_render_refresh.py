"""Refresh preview rendering at its producer without losing scientific identity."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..services.simulation_policy import SIMULATION_MANIFEST_SCHEMA, SIMULATION_RENDERER_VERSION
from .models import WorkflowRun


async def refresh_simulation_renderer(host: Any, run: WorkflowRun, direction: str) -> bool:
    """Reproject unchanged data before accepted-owner snapshot revalidation."""
    if run.options.get('run_experiment') is True:
        return False
    mode = str(run.options.get('non_experiment_evidence_mode') or 'design_only')
    if mode.strip().casefold() != 'synthetic_preview':
        return False
    root = Path(run.project_path).expanduser().resolve()
    from ..services.evidence_publication_recovery import pending_publication
    if pending_publication(root):
        return False
    from ..services.evidence_versions import version_plan, MANIFEST
    if (root / MANIFEST).is_file():
        plan = version_plan(root, direction, run.options)
        saved = json.loads((root / MANIFEST).read_text(encoding='utf-8-sig'))
        if saved.get('input_bundle_sha256') != plan['input_sha256']:
            # Resume must reach the interrupted owner without touching stale evidence.
            return False
    manifest_path = root / 'experiments/results/simulated/SIMULATION_MANIFEST.json'
    try:
        manifest = json.loads(manifest_path.read_text(encoding='utf-8-sig'))
    except FileNotFoundError:
        return False
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError('Existing simulation manifest is unreadable or malformed. Rebuild evidence at its producer in an explicitly requested new run; existing project data were not changed.') from error
    if not isinstance(manifest, dict):
        raise ValueError('Existing simulation manifest must be a JSON object. Rebuild evidence at its producer in an explicitly requested new run; existing project data were not changed.')
    if manifest.get('schema') != SIMULATION_MANIFEST_SCHEMA:
        raise ValueError('Unsupported simulation schema; regenerate evidence at its producer in a new run. Existing project artifacts were not changed.')
    renderer = manifest.get('renderer_version')
    if not isinstance(renderer, int) or isinstance(renderer, bool):
        raise ValueError('Simulation renderer version is missing or malformed. Rebuild evidence at its producer in an explicitly requested new run; existing project data were not changed.')
    if renderer != SIMULATION_RENDERER_VERSION:
        raise ValueError('Unsupported simulation renderer version. Rebuild evidence at its producer in an explicitly requested new run; existing project data were not changed.')
    from ..services.simulation_figure_refresh import refresh_existing_simulation_figures
    from ..services.simulation_paper_projection import refresh_simulation_paper_projection
    from ..services.simulation_table_publication_refresh import refresh_simulation_publication_tables

    assets = await refresh_existing_simulation_figures(root)
    table_changed = refresh_simulation_publication_tables(root)
    projection_changed = refresh_simulation_paper_projection(root)
    if assets or projection_changed or table_changed:
        await host._emit(run, 'simulation_figure_rendering_refreshed', {
            'node_id': run.checkpoint_node_id or 'preflight', 'asset_ids': assets,
            'scientific_data_changed': False,
            **({'paper_projection_changed': True} if projection_changed else {}),
            **({'table_projection_changed': True} if table_changed else {}),
        })
    return bool(assets) or projection_changed or table_changed
