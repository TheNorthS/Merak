"""Long scientific metric labels remain complete and uncropped at their producer."""

import csv

import pytest

from server.services.figure_artifacts import figure_artifact_registry
from server.services.paper_trusted_plot_source import match_trusted_plot
from server.services.simulation_comparison_plots import _ablation_delta_script
from server.services.simulation_plot_layout import wrap_plot_axis_text
from server.tests.test_simulation_figure_refresh import _render_local


METRIC = "Task manifest selected balanced accuracy or auroc task normalized (higher is better)"


def _code():
    return _ablation_delta_script("experiments/results/simulated/ablation.csv", "component_setting",
        METRIC, "simulated_ablation", {"fonts": ["DejaVu Sans"], "canvas": {"png_dpi": 200}}, "Full model", "maximize")


@pytest.mark.asyncio
async def test_long_axis_label_is_complete_without_edge_crop(tmp_path):
    data = tmp_path / "experiments/results/simulated/ablation.csv"
    data.parent.mkdir(parents=True)
    with data.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["component_setting", "value", "ci_low", "ci_high", "source_run_id"])
        writer.writeheader()
        for index, name in enumerate(("Full model", "Without observation model", "Without remapping", "Without shift-specific test")):
            writer.writerow(dict(component_setting=name, value=.672-index*.012, ci_low=.66-index*.012,
                                 ci_high=.684-index*.012, source_run_id="finite-fixture"))
    source = tmp_path / "figures/simulated/simulated_ablation.py"
    source.parent.mkdir(parents=True)
    code = _code()
    source.write_text(code, encoding="utf-8")
    await _render_local(source)
    assert figure_artifact_registry.raster_visual_quality_issues(source.with_suffix(".png")) == []
    import fitz
    with fitz.open(source.with_suffix(".pdf")) as document:
        text = " ".join(page.get_text() for page in document)
    assert METRIC.replace("_", " ").title().casefold() in " ".join(text.split()).casefold()


def test_wrapping_is_idempotent_and_remains_an_exact_trusted_template():
    code = _code()
    assert wrap_plot_axis_text(code) == code
    name, parameters, _ = match_trusted_plot(code)
    assert name == "ablation_delta" and parameters["metric"] == METRIC
    with pytest.raises(ValueError, match="exact current trusted"):
        match_trusted_plot(code + "\nprint('untrusted execution')\n")


@pytest.mark.parametrize("mutation", ["absolute_source", "absolute_data", "escaping_output", "escaping_stem"])
def test_layout_repair_cannot_write_outside_stage_even_with_declared_paths(mutation):
    from server.services.simulation_plot_layout_refresh import _plot_source_binding

    parameters = {"stem": "simulated_ablation", "data_path": "experiments/results/simulated/ablation.csv"}
    record = {"source": "figures/simulated/simulated_ablation.py", "outputs": {
        kind: f"figures/simulated/simulated_ablation.{kind}" for kind in ("pdf", "svg", "png")}}
    if mutation == "absolute_source":
        record["source"] = "D:/project/figures/simulated/simulated_ablation.py"
    elif mutation == "absolute_data":
        parameters["data_path"] = "D:/project/experiments/results/simulated/ablation.csv"
    elif mutation == "escaping_output":
        record["outputs"]["png"] = "../outside.png"
    else:
        parameters["stem"] = "../../outside"
    payload = {"data_files": [{"path": parameters["data_path"]}]}
    with pytest.raises(ValueError, match="Plot layout repair"):
        _plot_source_binding(parameters, record, payload)
