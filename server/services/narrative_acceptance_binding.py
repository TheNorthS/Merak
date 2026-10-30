"""Preserve accepted authored content across code updates using exact recorded inputs."""

import json
from pathlib import Path
import re
from typing import Any

from .workflow_inputs import artifact_state, artifact_state_equal


def accepted_narrative_inputs_match(root: Path, build: dict[str, Any],
                                    sources: list[Path], options: dict[str, Any]) -> bool:
    """Read existing proof only; never re-sign old provenance or waive current content checks."""
    run_id = str(options.get('resume_run_id') or '')
    if not re.fullmatch(r'[A-Za-z0-9_-]+', run_id):
        return False
    root = root.resolve()
    state_path = root / '.merak/runs' / (run_id + '.json')
    if not state_path.is_file():
        return False
    state = json.loads(state_path.read_bytes())
    phase = state.get('phases', {}).get('narrative', {})
    if phase.get('status') != 'accepted' or not phase.get('verdict_id') or not phase.get('reviewer'):
        return False
    names = [path.relative_to(root).as_posix() for path in sources if path.resolve().is_relative_to(root)]
    if len(names) != len(sources) or build.get('sources') != names:
        return False
    snapshot = phase.get('details', {}).get('artifact_snapshot')
    if not isinstance(snapshot, dict):
        return False
    for name in [*names, 'NARRATIVE_REPORT.md', '.merak/NARRATIVE_BUILD.json']:
        saved = snapshot.get(name)
        if not isinstance(saved, dict) or saved.get('kind') not in {'file', 'missing'}:
            return False
        if not artifact_state_equal(saved, artifact_state(root / name)):
            return False
    return True
