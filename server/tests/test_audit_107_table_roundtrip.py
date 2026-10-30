"""Actual table producer -> persisted source -> both strict consumers; fixed data only."""
import csv
from types import SimpleNamespace

import pytest

from server.services.publication_labels import publication_metric_axis_label
from server.services.simulation_asset_profile import simulation_asset_profile
from server.services.simulation_table_projection import simulation_tables
from server.services.simulation_primary_table import primary_comparison_panels
from server.services.simulation_table_publication import _bounded_primary_projection
from server.services.paper_table_source_labels import selected_table_source_records
from server.services.table_panel_reference_contract import _exact_panel_sources


@pytest.mark.parametrize("direction", ["maximize", "minimize"])
def test_actual_producer_roundtrip_and_numeric_tamper_rejection(tmp_path, direction):
    profile = simulation_asset_profile({"study_archetype": "algorithm_benchmark"})
    profile.update(contribution_type="objective_mechanism", coverage_x_label="Retained coverage",
                   coverage_y_label="Selective risk", slice_metric_axis_label="Error rate")
    rows = [{"dataset": f"Dataset {dataset}", "method": f"Method {method}", "value": "0.500",
             "ci_low": "0.400", "ci_high": "0.600", "secondary_value": "0.5",
             "stress_value": "0.4", "calibration_value": "0.05"} for dataset in range(4) for method in range(3)]
    field = profile["sensitivity_field"]
    ablation = [{field: "Focal", "delta": "+0.000"}, {field: "Without component", "delta": "-0.012"}]
    efficiency = [{"method": "Focal", **{f"resource_{index}": "0.5" for index in range(1, 6)}}]
    metric = publication_metric_axis_label("macro_f1", direction)
    text = simulation_tables(rows, ablation, [], [], efficiency, [], [], [], "shift", metric, profile, direction)
    source = tmp_path / "table.tex"
    source.write_text(text, encoding="utf-8")
    csv_path = tmp_path / "rows.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    frozen_csv = csv_path.read_bytes()
    binding = SimpleNamespace(label="tab:preview-main-results", data_path="rows.csv")
    payload = {"primary_metric": "macro_f1", "metric_direction": direction}
    panels = primary_comparison_panels(rows, binding.label)
    loaded = source.read_text(encoding="utf-8")
    records = selected_table_source_records(loaded)
    extra = {panel.label for panel in panels[1:]}
    for panel in panels:
        caption = records[panel.label]["caption"]
        assert "Assigned unitless scenario score" in caption
        assert "Macro-F1" not in caption
        assert "higher is better" not in caption and "lower is better" not in caption
    assert _bounded_primary_projection(tmp_path, payload, binding, records, loaded, extra) == loaded
    repeated = _bounded_primary_projection(tmp_path, payload, binding, records, loaded, extra)
    assert _bounded_primary_projection(
        tmp_path, payload, binding, selected_table_source_records(repeated), repeated, extra,
    ) == loaded
    separated = loaded.replace("\\end{table*}\n", "\\end{table*}\n\n% Preserve authored spacing\n", 1)
    assert _bounded_primary_projection(
        tmp_path, payload, binding, selected_table_source_records(separated), separated, extra,
    ) == separated
    _exact_panel_sources(rows, panels, binding, payload, loaded, [r["source"] for r in records.values()])
    tampered = loaded.replace("0.500 [0.400, 0.600]", "0.510 [0.400, 0.600]", 1)
    changed = selected_table_source_records(tampered)
    with pytest.raises(ValueError, match="frozen source rows"):
        _bounded_primary_projection(tmp_path, payload, binding, changed, tampered, extra)
    with pytest.raises(ValueError, match="Primary table panel"):
        _exact_panel_sources(rows, panels, binding, payload, tampered, [r["source"] for r in changed.values()])
    assert source.read_text(encoding="utf-8") == text and csv_path.read_bytes() == frozen_csv
