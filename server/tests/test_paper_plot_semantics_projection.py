"""Trusted paper-only axes/population semantics, no researcher project writes."""

from __future__ import annotations

import ast
import csv
import io
from pathlib import Path

import pytest

from server.services.paper_plot_semantics_projection import requires_source_presentation_projection
from server.services.paper_trusted_plot_source import match_trusted_plot, projected_plot_source
from server.services.simulation_comparison_plots import _multitask_matrix_script
from server.services.simulation_diagnostic_plots import _risk_coverage_script
from server.tests.test_paper_derived_figure_rendering import _style


def _csv(root: Path, rows: list[dict]) -> str:
    path = root / "experiments/results/simulated/values.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    stream = io.StringIO()
    writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    path.write_text(stream.getvalue(), encoding="utf-8")
    return path.relative_to(root).as_posix()


def _risk(root: Path, *, population: bool = True, repeated: bool = False) -> tuple[str, list[dict]]:
    rows = []
    for method in ("Joint", "Random"):
        for index in range(3):
            row = {"row_id": f"{method}-{index}", "method": method, "coverage": str(0.5 + index * 0.2),
                   "metric": "Selective risk", "value": str(0.03 + index * 0.01), "ci_low": "0.01", "ci_high": "0.07",
                   "risk": str(0.12 + index * 0.02), "risk_ci_low": str(0.10 + index * 0.02),
                   "risk_ci_high": str(0.14 + index * 0.02), "source_run_id": "fixture-owned"}
            if population:
                row["dataset"] = "Dataset A" if repeated else f"Dataset {index}"
            rows.append(row)
    relative = _csv(root, rows)
    return _risk_coverage_script(relative, _style(), "Retained coverage", "Selective risk", "risk"), rows


def test_matrix_corrects_axes_and_preserves_missing_or_reordered_method_rows(tmp_path):
    rows = [{"row_id": str(index), "dataset": dataset, "method": method, "metric": "macro_f1",
             "metric_direction": "maximize", "value": "0.6", "ci_low": "0.5", "ci_high": "0.7", "source_run_id": "fixture"}
            for index, (dataset, method) in enumerate((("A", "Joint"), ("A", "Random"), ("B", "Random")))]
    relative = _csv(tmp_path, rows)
    original = _multitask_matrix_script(relative, "Macro-F1", "matrix", _style(), "maximize")
    projected, name, _template = projected_plot_source(original, tmp_path, tmp_path / "paper/derived-figures/matrix", 1.0)
    assert name == "multitask_matrix"
    assert "Method index (legend order)" in projected and "Macro-F1 (higher is better)" in projected
    assert "methods.index(str(row['method']))" in projected and "_paper_markers" in projected
    assert "ci_low" in projected and "ci_high" in projected and "source_run_id" in projected
    assert match_trusted_plot(original)[0] == "multitask_matrix"
    assert list(csv.DictReader((tmp_path / relative).read_text().splitlines())) == rows


@pytest.mark.parametrize("population,repeated", [(False, False), (True, False), (True, True)])
def test_risk_groups_only_within_declared_population_and_keeps_metric(tmp_path, population, repeated):
    original, rows = _risk(tmp_path, population=population, repeated=repeated)
    projected, _name, _template = projected_plot_source(original, tmp_path, tmp_path / "paper/derived-figures/risk", 1.0)
    assert "Expected calibration error" not in projected
    assert "str(row.get('dataset') or '') == population" in projected
    assert "if len(selected) > 1" in projected
    assert "task_ax.set_ylabel(textwrap.fill('Selective risk'" in projected
    assert "by_dataset =" not in projected  # No row is silently replaced by one dataset key.
    assert "risk_ci_low" in projected and "risk_ci_high" in projected
    assert 'Generated dataset-coverage records' in projected
    assert 'Dataset-coverage observation' not in projected
    assert len(rows) == 6


def test_mixed_named_unknown_population_or_metric_direction_conflict_fails_closed(tmp_path):
    original, rows = _risk(tmp_path)
    relative = match_trusted_plot(original)[1]["data_path"]
    rows[0]["dataset"] = ""
    _csv(tmp_path, rows)
    with pytest.raises(ValueError, match="unknown populations"):
        projected_plot_source(original, tmp_path, tmp_path / "paper/out", 1.0)
    rows = [{"row_id": "a", "dataset": "A", "method": "Joint", "metric": "macro_f1",
             "metric_direction": "minimize", "value": "0.6", "ci_low": "0.5", "ci_high": "0.7", "source_run_id": "fixture"}]
    _csv(tmp_path, rows)
    matrix = _multitask_matrix_script(relative, "Macro-F1", "matrix", _style(), "maximize")
    with pytest.raises(ValueError, match="direction conflicts"):
        projected_plot_source(matrix, tmp_path, tmp_path / "paper/out", 1.0)


def test_semantic_owner_probe_recognizes_exact_current_templates_only(tmp_path):
    original, _rows = _risk(tmp_path)
    source = tmp_path / "figures/risk.py"
    source.parent.mkdir()
    source.write_text(original, encoding="utf-8")
    entry = {"source_path": "figures/risk.py"}
    assert requires_source_presentation_projection(tmp_path, entry)
    source.write_text(original + "\nrows = rows[:1]\n", encoding="utf-8")
    assert not requires_source_presentation_projection(tmp_path, entry)
    with pytest.raises(ValueError, match="exact current trusted"):
        projected_plot_source(source.read_text(), tmp_path, tmp_path / "paper/out", 1.0)


def test_risk_interval_never_mixes_a_partial_risk_family_with_generic_values():
    from server.services.paper_plot_semantics_projection import _INTERVAL_FAMILY
    scope = {"number": lambda value: None if value is None or value == "" else float(value)}
    exec(_INTERVAL_FAMILY, scope)
    interval = scope["_paper_metric_interval"]
    row = {"value": "0.03", "ci_low": "0.02", "ci_high": "0.04", "risk": "0.12",
        "risk_ci_low": "0.10", "risk_ci_high": "0.14"}
    assert interval(row, True) == (0.12, 0.10, 0.14)
    assert interval(row, False) == (0.03, 0.02, 0.04)
    row["risk_ci_low"] = ""
    with pytest.raises(ValueError, match="complete finite interval"):
        interval(row, True)


@pytest.mark.parametrize("population,repeated", [(False, False), (True, False), (True, True)])
def test_native_temporary_risk_pixels_retain_rows_and_correct_metric(tmp_path, monkeypatch, population, repeated):
    import fitz
    from matplotlib.axes import Axes
    from server.services.paper_derived_pixel_binding import _matplotlib_variants

    original, rows = _risk(tmp_path, population=population, repeated=repeated)
    code = projected_plot_source(original, tmp_path, tmp_path / "paper/out", 1.4)[0]
    captured = []
    bars = []
    original_errorbar = Axes.errorbar
    original_bar = Axes.bar
    def errorbar(self, x, y, *arguments, **keywords):
        if "label" in keywords:
            captured.append((list(x), list(y), keywords.get("linestyle")))
        return original_errorbar(self, x, y, *arguments, **keywords)
    monkeypatch.setattr(Axes, "errorbar", errorbar)
    def bar(self, x, height, *arguments, **keywords):
        bars.extend(list(height))
        return original_bar(self, x, height, *arguments, **keywords)
    monkeypatch.setattr(Axes, "bar", bar)
    variants = _matplotlib_variants(code.encode(), tmp_path / "paper/out.py")
    assert sum(len(values) for _x, values, _style in captured) == len(rows)
    assert len(bars) == (len(rows) if population else 0)
    assert [value for _x, values, _style in captured for value in values] == [float(row['risk']) for row in rows]
    if population:
        assert bars == [float(row['risk']) for row in rows]
    if population and not repeated:
        assert all(style == "none" for _x, _y, style in captured)
    else:
        assert all(style != "none" for _x, _y, style in captured)
    with fitz.open(stream=variants["pdf"], filetype="pdf") as document:
        text = document[0].get_text()
        assert "Expected calibration error" not in text and "Selective risk" in text
        assert "Joint" in text and "Random" in text
        assert 'observation' not in text.casefold()
        if population:
            assert 'Generated dataset-coverage records' in ' '.join(text.split())
            assert "Dataset" in text and "coverage=" in text
    (tmp_path / "semantic-preview.png").write_bytes(variants["png"])


@pytest.mark.asyncio
async def test_risk_presentation_packet_is_current_source_bound_and_preserves_all_original_bytes(tmp_path):
    import json
    from server.services.paper_derived_figure_binding import file_sha256
    from server.services.paper_derived_figure_rendering import derive_paper_figure, validate_derived_figure
    from server.services.paper_derived_pixel_binding import validate_pixel_binding
    from server.tests.test_paper_derived_figure_rendering import _entry, _placement

    entry = _entry(tmp_path)
    source, _rows = _risk(tmp_path)
    source_path = tmp_path / entry["source_path"]
    source_path.write_text(source)
    entry["source_sha256"] = file_sha256(source_path)
    relative = match_trusted_plot(source)[1]["data_path"]
    entry["metadata"]["source_data"] = [relative]
    entry["metadata"]["source_data_sha256"] = {relative: file_sha256(tmp_path / relative)}
    (tmp_path / "figures/FIGURE_MANIFEST.json").write_text(json.dumps({"schema": 1, "figures": [entry]}))
    originals = {path: path.read_bytes() for directory in ("figures", "experiments")
                 for path in (tmp_path / directory).rglob("*") if path.is_file()}
    packet = await derive_paper_figure(tmp_path, entry, _placement(tmp_path, entry))
    assert not validate_derived_figure(tmp_path, packet)
    assert not validate_pixel_binding(tmp_path, packet)
    assert packet["csv_inventory"][0]["rows"] == 6
    assert all(path.read_bytes() == value for path, value in originals.items())


@pytest.mark.asyncio
@pytest.mark.parametrize("template", ["multitask_matrix", "risk_coverage"])
async def test_long_public_names_full_paper_producer_retains_all_points_ci_and_readable_geometry(tmp_path, template):
    import json
    import fitz
    from server.services.paper_derived_figure_binding import file_sha256
    from server.services.paper_derived_figure_rendering import derive_paper_figure, validate_derived_figure
    from server.tests.test_paper_derived_figure_rendering import _entry, _placement

    entry = _entry(tmp_path)
    names = ["CSFS joint shared-private objective", "BENDR-style contextual contrastive pretraining",
             "Waveform or latent masked-prediction pretraining", "Channel-subset-only shared objective",
             "Frequency-view-only shared objective", "Full-latent alignment without private factorization",
             "Shuffled cross-view pairing control", "Random initialization"]
    datasets = ["FACED / emotion", "SEED-V / emotion", "PhysioNet-MI / motor imagery", "SHU-MI / motor imagery",
                "ISRUC / sleep staging", "CHB-MIT / seizure", "TUEV / event type", "TUAB / abnormality"]
    if template == "multitask_matrix":
        rows = [{"row_id": f"{index}-{target}", "dataset": dataset, "method": method,
                 "metric": "macro_f1", "metric_direction": "maximize", "value": str(0.5 + index * 0.025),
                 "ci_low": str(0.49 + index * 0.025), "ci_high": str(0.51 + index * 0.025), "source_run_id": "fixture"}
                for index, method in enumerate(names) for target, dataset in enumerate(datasets)]
    else:
        names, datasets = names[:3] + names[-1:], datasets[:5]
        rows = [{"row_id": f"{index}-{target}", "dataset": dataset, "method": method, "metric": "Selective risk",
                 "coverage": str(0.5 + target * 0.1), "value": str(0.02 + index * 0.012 + target * 0.004),
                 "ci_low": str(0.018 + index * 0.012 + target * 0.004), "ci_high": str(0.022 + index * 0.012 + target * 0.004),
                 "risk": str(0.1 + index * 0.022 + target * 0.012), "risk_ci_low": str(0.095 + index * 0.022 + target * 0.012),
                 "risk_ci_high": str(0.105 + index * 0.022 + target * 0.012), "source_run_id": "fixture"}
                for index, method in enumerate(names) for target, dataset in enumerate(datasets)]
    relative = _csv(tmp_path, rows)
    source = (_multitask_matrix_script(relative, "Macro-F1", "matrix", _style(), "maximize") if template == "multitask_matrix"
              else _risk_coverage_script(relative, _style(), "Retained coverage", "Selective risk", "risk"))
    path = tmp_path / entry["source_path"]
    path.write_text(source)
    entry["source_sha256"] = file_sha256(path)
    entry["metadata"]["source_data"] = [relative]
    entry["metadata"]["source_data_sha256"] = {relative: file_sha256(tmp_path / relative)}
    (tmp_path / "figures/FIGURE_MANIFEST.json").write_text(json.dumps({"schema": 1, "figures": [entry]}))
    protected = {value: value.read_bytes() for value in (path, tmp_path / relative)}
    packet = await derive_paper_figure(tmp_path, entry, _placement(tmp_path, entry))
    assert packet["csv_inventory"][0]["rows"] == (64 if template == "multitask_matrix" else 20)
    assert packet["render_attempts"][-1]["minimum_placed_font_bp"] >= 8.5
    assert packet["render_attempts"][-1]["text_geometry_findings"] == []
    assert not validate_derived_figure(tmp_path, packet)
    assert all(value.read_bytes() == before for value, before in protected.items())
    with fitz.open(tmp_path / packet["output_path"]) as document:
        text = " ".join(document[0].get_text().split())
    assert all(" ".join(name.split()) in text for name in names)


@pytest.mark.asyncio
async def test_normal_print_owner_derives_semantics_even_with_readable_original_fonts(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from server.services import paper_print_repair as repair
    from server.services import paper_derived_figure_rendering as derived
    from server.services import paper_print_projection as projection
    from server.services.publication_print_contract import read_publication_print_contract

    original, _rows = _risk(tmp_path)
    source = tmp_path / "figures/risk.py"
    source.parent.mkdir()
    source.write_text(original)
    entry = {"id": "risk", "source_path": "figures/risk.py", "output_path": "figures/risk.pdf"}
    (tmp_path / "figures/FIGURE_MANIFEST.json").write_text(__import__("json").dumps({"figures": [entry]}))
    contract = {"placements": [{"graphic_relative": "figures/risk.pdf", "width_bp": 420}], "contract_sha256": "fixture"}
    monkeypatch.setattr("server.services.publication_print_contract.read_publication_print_contract", lambda *_args: SimpleNamespace(to_dict=lambda: contract))
    monkeypatch.setattr(repair, "_placed_minimum", lambda *_args: 12.0)
    monkeypatch.setattr(projection, "restore_print_entrypoint", lambda *_args: None)
    monkeypatch.setattr(projection, "install_print_projection", lambda *_args: None)
    observed = []
    async def generate(*arguments):
        observed.append(arguments)
        return {"asset_id": "risk"}
    monkeypatch.setattr(derived, "derive_paper_figure", generate)
    assert await repair.prepare_print_figures(tmp_path) == [{"asset_id": "risk"}]
    assert len(observed) == 1
