"""Bind explicit local primary rows to the real current publication producer."""

import csv
from pathlib import Path

from server.services.paper_table_source_labels import selected_table_source_records
from server.services.publication_labels import publication_metric_axis_label
from server.services.simulation_primary_table import render_primary_comparison_panels


def bind_fixture_primary_table(root: Path, payload: dict) -> None:
    """Fixture setup only; no runtime gate, model or scientific generator executes."""
    table = root / payload["paper_table"]
    with (root / "experiments/results/simulated/main_comparison.csv").open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    original = table.read_text(encoding="utf-8")
    records = selected_table_source_records(original)
    label = "tab:preview-main-results"
    rendered = render_primary_comparison_panels(rows, publication_metric_axis_label(payload["primary_metric"], payload["metric_direction"]),
        records[label]["caption"], label)
    table.write_bytes(original.replace(records[label]["source"], rendered.rstrip("\n"), 1).encode("utf-8"))
    import hashlib
    payload["paper_table_sha256"] = hashlib.sha256(table.read_bytes()).hexdigest()
