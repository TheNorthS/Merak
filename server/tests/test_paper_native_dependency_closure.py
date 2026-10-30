"""Native print fixes reopen every dependent gate without accepting artifacts."""

import hashlib
from pathlib import Path

import pytest

from server.services.paper_stage_validator_signature import stage_validator_signature
from server.utils.runtime_source_root import server_source_root
from server.workflows.engine import WorkflowEngine
from server.workflows.engine_revision_signature import _bind_validator_sources


_NATIVE = ("figure_renderer.py", "figure_semantic_rendering.py", "scientific_scene_geometry.py",
           "scientific_scene_panel_figure.py", "figurespec_layout_policy.py", "deterministic_figure_freshness.py")


@pytest.mark.parametrize("source_name", _NATIVE)
def test_native_implementation_changes_reopen_paper_review_slides_risk_and_stage_cache(source_name, monkeypatch):
    read_bytes, changed = Path.read_bytes, [False]

    def changed_source(path):
        content = read_bytes(path)
        return content + b"\n# Pure source-closure fixture" if changed[0] and path.name == source_name else content

    monkeypatch.setattr(Path, "read_bytes", changed_source)

    def signatures():
        revision = []
        for node in ("paper", "review", "ppt"):
            digest = hashlib.sha256()
            _bind_validator_sources(digest, node)
            revision.append(digest.hexdigest())
        return [*revision, WorkflowEngine._risk_audit_validator_signature({"run_experiment": False}),
                *(stage_validator_signature(stage) for stage in ("consistency", "assembly"))]

    before = signatures()
    changed[0] = True
    assert all(left != right for left, right in zip(before, signatures(), strict=True))


@pytest.mark.parametrize("relative", ["services/paper_print_producer_findings.py",
    "workflows/paper_runtime_failure_diagnostics.py", "contracts/repairs.py",
    "services/paper_draft_state.py", "services/local_compile_process.py",
    "services/latex_compile_execution.py", "services/windows_compile_job.py"])
def test_print_runtime_capability_sources_belong_to_existing_preparation_and_risk_closures(relative):
    from server.services.paper_preparation_sources import paper_preparation_implementation_paths
    from server.services.risk_validator_sources import risk_validator_source_paths

    root = server_source_root()
    dependency = root / relative
    assert dependency.is_file()
    assert dependency in paper_preparation_implementation_paths(root / "services")
    assert dependency in risk_validator_source_paths(root / "services")
