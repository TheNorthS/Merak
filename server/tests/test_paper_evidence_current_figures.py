"""Only current-portfolio figures may enter a paper evidence snapshot."""

from __future__ import annotations

from pathlib import Path

import pytest

from server.services import paper_evidence_snapshot


def _entry(identity: str) -> dict:
    return {
        "id": identity, "output_path": f"figures/{identity}.pdf",
        "metadata": {
            "semantic_key": identity, "scientific_role": "method",
            "evidence_status": "implemented_design",
        },
    }


@pytest.mark.parametrize("plan,expected", [
    ({"assets": [
        {"id": "method_architecture", "kind": "figure"},
        {"id": "evaluation_design", "kind": "figure"},
    ]}, {"method_architecture", "evaluation_design"}),
    ({"assets": []}, set()),
    ({}, {"method_architecture", "core_mechanism", "evaluation_design"}),
])
def test_paper_snapshot_excludes_unplanned_legacy_core_figure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    plan: dict, expected: set[str],
) -> None:
    entries = [_entry(identity) for identity in (
        "method_architecture", "core_mechanism", "evaluation_design",
    )]
    monkeypatch.setattr(paper_evidence_snapshot.scientific_asset_service, "load", lambda _root: plan)
    monkeypatch.setattr(
        paper_evidence_snapshot.figure_artifact_registry,
        "paper_ready_entries", lambda _root: entries,
    )
    evidence = paper_evidence_snapshot.collect_paper_evidence(tmp_path)
    assert {item["id"] for item in evidence.figures} == expected
