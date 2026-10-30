"""Render fixed local rows to verify comparison-legend publication geometry."""

from __future__ import annotations

import csv
from pathlib import Path

import fitz
import pytest
from PIL import Image

from server.services.simulation_comparison_plots import _multitask_matrix_script


_METHODS = (
    "SSD-LP source-constrained shared representation",
    "Matched single-latent structured latent prediction control",
    "EEG2Rep-style informative latent-prediction control",
    "EEG-JEPA-style structured latent-prediction control where reproducible",
    "Restricted-readout ablation with source-state task access",
    "BENDR-style contrastive masked-prediction control",
)


def _fixture_rows(path: Path, method_count: int, dataset_count: int) -> None:
    path.parent.mkdir(parents=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=(
            "row_id", "method", "dataset", "value", "ci_low", "ci_high",
            "source_run_id", "mean_task_rank",
        ))
        writer.writeheader()
        for dataset in range(dataset_count):
            for index, method in enumerate(_METHODS[:method_count]):
                writer.writerow({
                    "row_id": f"fixture-{dataset}-{index}", "method": method,
                    "dataset": f"Registered dataset {dataset + 1} / downstream task",
                    "value": 0.5 + index * 0.02, "ci_low": 0.48 + index * 0.02,
                    "ci_high": 0.52 + index * 0.02,
                    "source_run_id": "local-layout-fixture", "mean_task_rank": index + 1,
                })


@pytest.mark.parametrize("method_count,dataset_count", [(1, 1), (3, 3), (6, 8)])
def test_full_method_names_fit_without_canvas_widening(
    tmp_path: Path, method_count: int, dataset_count: int,
) -> None:
    data = tmp_path / "experiments/results/simulated/main_comparison.csv"
    _fixture_rows(data, method_count, dataset_count)
    before = data.read_bytes()
    script = tmp_path / "figures/simulated/simulated_main_comparison.py"
    script.parent.mkdir(parents=True)
    code = _multitask_matrix_script(
        data.relative_to(tmp_path).as_posix(), "Macro-F1", script.stem,
        {"fonts": ["DejaVu Sans"], "canvas": {"png_dpi": 200}}, "maximize",
    )
    namespace = {"__file__": str(script), "__name__": "__layout_fixture__"}
    exec(compile(code, str(script), "exec"), namespace)

    assert data.read_bytes() == before
    assert namespace["legend_columns"] <= 2
    for original, label in zip(_METHODS[:method_count], namespace["legend_labels"]):
        assert original in " ".join(label.splitlines())
    assert all("\\n" not in panel.get_title() for panel in namespace["axes_flat"])
    with Image.open(script.with_suffix(".png")) as image:
        width, height = image.size
        assert 0.7 <= width / height <= 4.2
        assert width <= 7.8 * 200
    with fitz.open(script.with_suffix(".pdf")) as document:
        text = " ".join(document[0].get_text().split())
        for method in _METHODS[:method_count]:
            assert method in text
        spans = [span for block in document[0].get_text("dict")["blocks"]
                 if block.get("type") == 0 for line in block["lines"]
                 for span in line["spans"] if span.get("text", "").strip()]
        assert spans and min(span["size"] for span in spans) >= 8
