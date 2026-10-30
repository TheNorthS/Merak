"""Native print projections keep long condition names, every value, and readable panels."""

import csv
import io

import fitz
import pytest

from server.services.paper_derived_figure_binding import pdf_print_geometry
from server.services.paper_trusted_plot_source import projected_plot_source
from server.services.simulation_comparison_plots import _robustness_script
from server.services.simulation_diagnostic_plots import _risk_coverage_script
from server.tests.test_paper_derived_figure_rendering import _style


@pytest.mark.parametrize("template", ["robustness", "risk_coverage"])
def test_long_names_fit_at_narrow_manuscript_width_without_changing_data(tmp_path, template):
    names = ["MAMP-EEG with controlled montage-remapping supervision",
             "GMAEEG-style graph masked-autoencoder baseline when coordinate provenance is valid"]
    rows = []
    for method in names:
        for index in range(5):
            rows.append({"method": method, "dataset": f"Dataset {index} / registered task",
                "coverage": str(.5 + index * .1), "missing_channel_rate": str(index * .1),
                "metric": "Selective risk", "value": str(.1 + index * .02), "ci_low": str(.09 + index * .02),
                "ci_high": str(.11 + index * .02), "risk": str(.2 + index * .02),
                "risk_ci_low": str(.19 + index * .02), "risk_ci_high": str(.21 + index * .02), "source_run_id": "fixture"})
    data = tmp_path / "experiments/results/simulated/values.csv"
    data.parent.mkdir(parents=True)
    stream = io.StringIO()
    writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    data.write_text(stream.getvalue())
    before = data.read_bytes()
    relative = data.relative_to(tmp_path).as_posix()
    code = (_robustness_script(relative, "missing_channel_rate", "Registered endpoint with a deliberately long public metric name", _style(), "plot")
            if template == "robustness" else _risk_coverage_script(relative, _style(), "Retained coverage", "Selective risk", "plot"))
    output = tmp_path / "paper/figure"
    output.parent.mkdir()
    projected = projected_plot_source(code, tmp_path, output, 1.4)[0]
    exec(compile(projected, "plot.py", "exec"), {"__file__": "plot.py"})
    geometry = pdf_print_geometry(output.with_suffix(".pdf"), {"width_bp": 372.24})
    assert geometry["minimum_placed_font_bp"] >= 8
    assert geometry["text_geometry_findings"] == []
    with fitz.open(output.with_suffix(".pdf")) as document:
        text = " ".join(document[0].get_text().split())
    assert all(name in text for name in names)
    assert data.read_bytes() == before
