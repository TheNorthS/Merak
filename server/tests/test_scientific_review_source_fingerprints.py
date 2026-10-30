"""Changed review producers and scientific truth policies reopen real caches."""

import hashlib
from pathlib import Path

import pytest

from server.workflows.engine_revision_signature import _bind_validator_sources


_REVIEW = (
    "review_contract_sources.py", "review_execution.py", "review_visuals.py",
    "review_loop.py", "review_snapshot_reuse.py", "review_visual_artifact_evidence.py",
    "review_visual_trace_evidence.py", "review_visual_attachment_evidence.py",
    "paper_print_repair.py", "paper_print_projection.py", "paper_pdf_quality.py",
)
_SCIENTIFIC = (
    "scientific_contract_sources.py", "protocol_conformance.py", "experiment_runner.py",
    "simulation_claim_decisions.py", "simulation_claim_decision_report.py",
    "simulation_claim_evidence.py", "simulation_benchmark.py",
    "simulation_result_analysis.py", "scientific_narrative.py", "narrative_rendering.py",
    "narrative_evidence.py", "narrative_source_bindings.py",
)


def _replace_source(monkeypatch, source_name):
    original, changed = Path.read_bytes, [False]

    def read(path):
        if path.name == source_name:
            return b"changed implementation" if changed[0] else b"original implementation"
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", read)
    return changed


@pytest.mark.parametrize("node,source_name", [
    *(("review", name) for name in _REVIEW),
    *((node, name) for node in ("exp-run", "results", "narrative", "paper", "review") for name in _SCIENTIFIC),
])
def test_real_revision_and_runtime_capability_reopen(node, source_name, tmp_path, monkeypatch):
    from server.services.skill_registry import skill_registry
    from server.workflows.engine import WorkflowEngine

    host = WorkflowEngine()
    monkeypatch.setattr(host, "_ensure_agent_tools", lambda: None)
    monkeypatch.setattr(host, "_workflow_stage_required_tools", lambda *_args: set())
    monkeypatch.setattr(skill_registry, "get_skill", lambda *_args: None)
    changed = _replace_source(monkeypatch, source_name)
    digest = hashlib.sha256()
    _bind_validator_sources(digest, node)
    options = {"run_experiment": False, "non_experiment_evidence_mode": "design_only"}
    runtime = host._revision_runtime_signature(str(tmp_path), node, options)
    changed[0] = True
    revised = hashlib.sha256()
    _bind_validator_sources(revised, node)
    assert revised.hexdigest() != digest.hexdigest()
    assert host._revision_runtime_signature(str(tmp_path), node, options) != runtime


@pytest.mark.parametrize("source_name", [*_REVIEW, *_SCIENTIFIC])
def test_accepted_risk_cache_requires_current_implementation(source_name, monkeypatch):
    from server.workflows.engine import WorkflowEngine

    host = WorkflowEngine()
    changed = _replace_source(monkeypatch, source_name)
    previous = host._risk_audit_validator_signature({})
    changed[0] = True
    assert host._risk_audit_validator_signature({}) != previous


def test_review_dependencies_use_frozen_source_mirror(tmp_path, monkeypatch):
    from server.utils import runtime_source_root
    from server.services.risk_validator_sources import risk_validator_source_paths

    mirror, loaded = tmp_path / "merak-source/server", tmp_path / "server"
    (mirror / "services").mkdir(parents=True)
    monkeypatch.setattr(runtime_source_root, "__file__", str(loaded / "utils/runtime_source_root.py"))
    monkeypatch.setattr(runtime_source_root.sys, "frozen", True, raising=False)
    monkeypatch.setattr(runtime_source_root.sys, "_MEIPASS", str(tmp_path), raising=False)
    paths = risk_validator_source_paths(loaded / "services")
    assert mirror / "workflows/review_contract_sources.py" in paths
    assert mirror / "services/simulation_claim_decision_report.py" in paths
    native = {tmp_path / "merak-skills/figure-spec/scripts" / name
              for name in ("figure_renderer.py", "figure_semantic_rendering.py")}
    assert native.issubset(paths)
    assert all(path.is_relative_to(mirror) or path in native for path in paths)
