"""Interrupted cross-section review resumes without reauthoring unchanged downstream sections."""

import json

import pytest

from server.services.paper_deferred_rebind import deferred_rebind_current
from server.services.paper_drafting import AUTHOR_STAGE_ORDER, PAPER_STAGE_LABELS
from server.services.paper_gate_reporting import _active_stage
from server.tests._paper_freshness_complete_support import completed_local_manuscript
from server.tests.test_paper_stage_validator_cache import _coordinator


@pytest.mark.asyncio
async def test_deferred_author_rebind_survives_restart_and_keeps_consistency_blocking(tmp_path):
    service, paths = completed_local_manuscript(tmp_path)
    related = paths["sections"] / "02_related_work.tex"
    related.write_text(related.read_text() + "\nThe registered comparison also distinguishes eligibility assumptions.\n")
    service.mark_stage(paths, "related_work", "completed", attempt=2, review=service.validate_stage(tmp_path, "related_work"))
    coordinator = _coordinator(tmp_path, service, paths)
    coordinator.target_stage_issues = {"related_work": ["scoped repair"], "consistency": ["review all current sections"]}
    protected = {}
    for stage in AUTHOR_STAGE_ORDER:
        if stage in {"related_work", "consistency"}:
            continue
        protected.update({path: path.read_bytes() for path in service.stage_outputs(paths, stage)})
        await coordinator._run_stage(stage)
    service.mark_stage(paths, "consistency", "pending", attempt=0, error="model interrupted")
    state = json.loads(paths["state"].read_text())
    assert deferred_rebind_current(paths, state, "method")
    active = _active_stage(paths, state, AUTHOR_STAGE_ORDER, service.stage_contract_version("assembly"),
                           service.stage_is_current, service.stage_contract_version)
    assert active["stage"] == "consistency"
    assert not service.stage_is_current(paths, state, "method")
    resumed = _coordinator(tmp_path, service, paths)
    await resumed._run_stage("method")
    assert all(path.read_bytes() == original for path, original in protected.items())
    method = paths["sections"] / "03_method.tex"
    method.write_bytes(method.read_bytes() + b"changed after deferral")
    assert not deferred_rebind_current(paths, state, "method")
