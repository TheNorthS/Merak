"""Declared focal mechanisms remain separate scientific objects."""

import json
from pathlib import Path

import pytest

from server.services.figure_mechanism_requirements import (
    required_mechanism_labels, validate_required_mechanisms,
)


def test_excludes_nonfocal_protocol_but_requires_three_method_mechanisms(
    tmp_path: Path,
) -> None:
    figures = tmp_path / "figures"
    figures.mkdir()
    (figures / "FIGURE_SPECS.json").write_text(json.dumps({
        "figures": [{
            "id": "method_architecture", "scientific_role": "method",
            "scientific_question": "How do the proposed objectives cooperate?",
            "publication_labels": [
                {"id": "method.mechanism.1", "display_text": "Temporal-local consistency"},
                {"id": "method.mechanism.2", "display_text": "Spectral-view consistency"},
                {"id": "method.mechanism.3", "display_text": "Local-topological consistency"},
                {"id": "method.mechanism.4", "display_text": "Matched-budget attribution protocol"},
            ],
            "scientific_scene": {
                "objects": [
                    {"id": "input", "kind": "input", "label": "Observed signal"},
                    {"id": "encoder", "kind": "operation", "label": "Shared encoder"},
                    {"id": "ledger", "kind": "input", "label": "Matched budget ledger"},
                ],
                "relations": [
                    {"from": "input", "to": "encoder", "kind": "data"},
                    {"from": "ledger", "to": "encoder", "kind": "constraint"},
                ],
            },
        }],
    }), encoding="utf-8")
    labels = required_mechanism_labels(tmp_path, "method_architecture")
    assert labels == [
        "Temporal-local consistency", "Spectral-view consistency",
        "Local-topological consistency",
    ]


def test_rejects_collapsed_factorized_mechanism() -> None:
    mechanism_ir = {"primitives": [
        {"id": "all_constraints", "public_label": "Factorized consistency"},
    ]}
    with pytest.raises(ValueError, match="separate primitive"):
        validate_required_mechanisms(
            mechanism_ir, ["Temporal-local consistency", "Spectral-view consistency"],
        )
