from __future__ import annotations

import json
from pathlib import Path

from server.services.scientific_assets import scientific_asset_service


def test_nested_json_parser_preserves_condition_and_completed_metrics(
    tmp_path: Path,
) -> None:
    result_dir = tmp_path / "experiments" / "results"
    result_dir.mkdir(parents=True)
    path = result_dir / "nested.json"
    path.write_text(
        json.dumps({
            "method": "Proposed",
            "subgroups": [{
                "subgroup": "External cohort",
                "metric": "AUROC",
                "value": 0.84,
                "ci_low": 0.80,
                "ci_high": 0.88,
            }],
        }),
        encoding="utf-8",
    )

    records = scientific_asset_service._records_from_json(tmp_path, path)

    assert len(records) == 1
    assert records[0].method == "Proposed"
    assert records[0].metric == "AUROC"
    assert records[0].condition_name == "subgroup"
    assert records[0].condition_value == "External cohort"
    assert records[0].role == "robustness"
    assert records[0].ci_low == 0.80
    assert records[0].ci_high == 0.88


def test_wide_json_ignores_seed_and_epoch_fields(tmp_path: Path) -> None:
    result_dir = tmp_path / "experiments" / "results"
    result_dir.mkdir(parents=True)
    path = result_dir / "wide.json"
    path.write_text(
        json.dumps({
            "model": "Baseline",
            "seed": 7,
            "epoch": 12,
            "accuracy": 0.75,
            "loss": 0.42,
        }),
        encoding="utf-8",
    )

    records = scientific_asset_service._records_from_json(tmp_path, path)

    assert {item.metric.casefold() for item in records} == {"accuracy", "loss"}
    assert {item.seed for item in records} == {"7"}
