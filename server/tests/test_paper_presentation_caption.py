"""Source-bound paper caption fixtures; original science/prose are never rewritten."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from server.services.paper_derived_figure_binding import bound_original_inputs, file_sha256, stable_json_sha256
from server.services.paper_derived_figure_rendering import derive_paper_figure, validate_derived_figure
from server.services.paper_presentation_caption import caption_contracts
from server.services import paper_print_projection as projection
from server.tests.test_paper_derived_figure_rendering import _entry, _pdf
from server.tests.test_paper_plot_semantics_projection import _risk


def _fixture(root: Path, *, population: bool = True, repeated: bool = False):
    entry = _entry(root)
    source, _rows = _risk(root, population=population, repeated=repeated)
    (root / entry["source_path"]).write_text(source, encoding="utf-8")
    entry["source_sha256"] = file_sha256(root / entry["source_path"])
    data = "experiments/results/simulated/values.csv"
    metadata = entry["metadata"]
    metadata.update(source_data=[data], source_data_sha256={data: file_sha256(root / data)}, label="fig:declared-risk")
    manifest = root / "figures/FIGURE_MANIFEST.json"
    manifest.write_text(json.dumps({"schema": 1, "figures": [entry]}), encoding="utf-8")
    section = root / "paper/sections/05_results.tex"
    section.parent.mkdir()
    _pdf(root / "figures/unrelated.pdf", fontsize=12)
    authored = "Reviewed source prose keeps its scientific claim.\n% Other comment stays exact.\n"
    other = (r"\begin{figure}\includegraphics[width=.7\textwidth]{../figures/unrelated.pdf}"
             r"\caption{An unrelated authored caption {with nested text}.}\label{fig:other}\end{figure}" + "\n")
    figure = (r"\begin{figure*}[t]\centering\includegraphics[width=.94\textwidth]{../"
        + entry["output_path"] + r"}\caption{Old curves {with nested notation} and \{escaped braces\}.}"
        + r"\label{fig:declared-risk}\end{figure*}" + "\n")
    section.write_text(authored + other + figure, encoding="utf-8")
    main = root / "paper/main.tex"
    main.write_text(r"\documentclass{article}" + "\n" + r"\textwidth 396bp\begin{document}\input{sections/05_results}\end{document}", encoding="utf-8")
    output = root / "paper/derived-figures/local-risk/figure.pdf"
    output.parent.mkdir(parents=True)
    output.write_bytes(b"finite local binding only; native fixture derives real pixels separately")
    bound, inventory = bound_original_inputs(root, entry)
    packet = {"asset_id": entry["id"], "source": entry["source_path"], "label": metadata["label"],
        "original_path": entry["output_path"], "output_path": output.relative_to(root).as_posix(),
        "original_entry_sha256": stable_json_sha256(entry), "original_inputs_sha256": bound, "csv_inventory": inventory}
    return entry, packet, section, authored + other


def _transform(root: Path, packet: dict, section: Path) -> str:
    sources = {section: section.read_text(encoding="utf-8")}
    graphics = {root / packet["original_path"]: root / packet["output_path"]}
    return projection._transform_sources(root, sources, graphics, [packet])[section]


@pytest.mark.parametrize("population,repeated", [(True, False), (True, True), (False, False)])
def test_source_populations_determine_caption_not_old_curve_words(tmp_path, population, repeated):
    entry, packet, section, prefix = _fixture(tmp_path, population=population, repeated=repeated)
    before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    changed = _transform(tmp_path, packet, section)
    assert changed.startswith(prefix)
    assert "Recorded Selective risk values and retained-risk records at the declared retained coverages" in changed
    assert "generated scenario labels, not measurements from those datasets" in changed
    assert "assigned scenario bounds, not population confidence intervals" in changed
    assert "observations" not in changed
    assert "Old curves" not in changed and "Expected calibration error" not in changed
    if population and not repeated:
        assert "different datasets are not joined" in changed and "within-dataset coverage effect" in changed
        assert "Lines and shaded" not in changed
    else:
        assert "Lines and shaded intervals connect only" in changed
    assert packet["output_path"].removeprefix("paper/") in changed
    assert all(p.read_bytes() == data for p, data in before.items())
    assert caption_contracts(tmp_path, [packet])[tmp_path / entry["output_path"]]["label"] == "fig:declared-risk"


@pytest.mark.parametrize("defect", ["missing_label", "wrong_label", "missing_caption", "short_caption", "star_caption",
    "two_captions", "unbalanced", "duplicate_float", "wrong_graphic", "second_graphic", "commented_float",
    "packet_label", "entry_pin", "csv_pin", "inventory", "source_data"])
def test_ambiguous_or_unbound_caption_identity_is_rejected_before_any_write(tmp_path, defect):
    _entry_value, packet, section, _prefix = _fixture(tmp_path)
    text = section.read_text()
    if defect == "missing_label": text = text.replace(r"\label{fig:declared-risk}", "")
    elif defect == "wrong_label": text = text.replace("fig:declared-risk", "fig:unknown")
    elif defect == "missing_caption": text = text.replace(r"\caption{Old curves", r"\other{Old curves")
    elif defect == "short_caption": text = text.replace(r"\caption{Old curves", r"\caption[Old short caption]{Old curves")
    elif defect == "star_caption": text = text.replace(r"\caption{Old curves", r"\caption*{Old curves")
    elif defect == "two_captions": text = text.replace(r"\label{fig:declared-risk}", r"\caption{Another caption}\label{fig:declared-risk}")
    elif defect == "unbalanced": text = text.replace(r" and \{escaped braces\}.}", r" and \{escaped braces\}.")
    elif defect == "duplicate_float": text += text[text.index(r"\begin{figure*}"):]
    elif defect == "wrong_graphic": text = text.replace(packet["original_path"], "figures/not-declared.pdf")
    elif defect == "second_graphic": text = text.replace(r"\label{fig:declared-risk}", r"\includegraphics{../figures/other.pdf}\label{fig:declared-risk}")
    elif defect == "commented_float": text = text.replace(r"\begin{figure*}", r"%\begin{figure*}")
    elif defect == "packet_label": packet["label"] = "fig:another"
    elif defect == "entry_pin": packet["original_entry_sha256"] = "0" * 64
    elif defect == "csv_pin": packet["original_inputs_sha256"]["experiments/results/simulated/values.csv"] = "0" * 64
    elif defect == "inventory": packet["csv_inventory"][0]["rows"] += 1
    else: (tmp_path / "experiments/results/simulated/values.csv").write_text("method,value\nchanged,0.99\n")
    section.write_text(text)
    before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    with pytest.raises(ValueError):
        _transform(tmp_path, packet, section)
    assert all(p.read_bytes() == data for p, data in before.items())


def test_nonrisk_and_no_packet_captions_stay_byte_exact(tmp_path):
    entry = _entry(tmp_path)
    source = tmp_path / "paper/main.tex"
    source.write_text(source.read_text() + r"\caption{Original matrix caption remains.}")
    derived = tmp_path / "paper/derived-figures/matrix/figure.pdf"
    derived.parent.mkdir(parents=True)
    derived.write_bytes(b"finite local path fixture")
    packet = {"source": entry["source_path"], "asset_id": entry["id"], "original_path": entry["output_path"],
              "output_path": derived.relative_to(tmp_path).as_posix()}
    text = source.read_text()
    transformed = projection._transform_sources(tmp_path, {source: text}, {tmp_path / entry["output_path"]: derived}, [packet])
    assert r"\caption{Original matrix caption remains.}" in transformed[source]
    assert projection._transform_sources(tmp_path, {source: text}, {}, []) == {}


@pytest.mark.asyncio
async def test_native_risk_pixels_and_caption_share_print_proof_and_resigned_caption_forgery_blocks(tmp_path):
    from server.services.publication_print_contract import read_publication_print_contract

    entry, _binding_packet, section, prefix = _fixture(tmp_path)
    original_main = (tmp_path / "paper/main.tex").read_bytes()
    originals = {p: p.read_bytes() for name in ("figures", "experiments")
                 for p in (tmp_path / name).rglob("*") if p.is_file()}
    authored = section.read_bytes()
    full = read_publication_print_contract(tmp_path).to_dict()
    placed = next(item for item in full["placements"] if item["graphic_relative"] == entry["output_path"])
    placement = {**placed, "minimum_font_bp": full["minimum_font_bp"], "target_font_bp": full["target_font_bp"],
                 "contract_sha256": full["contract_sha256"], "print_contract": full}
    packet = await derive_paper_figure(tmp_path, entry, placement)
    assert validate_derived_figure(tmp_path, packet) == []
    projection.install_print_projection(tmp_path, [packet])
    assert projection.validate_print_projection(tmp_path) == []
    derived = tmp_path / "paper/derived-figures/tex/sections/05_results.tex"
    text = derived.read_text()
    assert text.startswith(prefix) and "different datasets are not joined" in text
    assert "Lines and shaded" not in text and "Old curves" not in text
    assert section.read_bytes() == authored
    assert (tmp_path / "paper/derived-figures/ORIGINAL_MAIN.tex").read_bytes() == original_main
    assert all(p.read_bytes() == data for p, data in originals.items())
    before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    projection.install_print_projection(tmp_path, [packet])
    assert all(p.read_bytes() == data for p, data in before.items())
    receipt = tmp_path / projection.RECEIPT
    payload = json.loads(receipt.read_text())
    derived.write_text(text.replace("do not establish a within-dataset coverage effect", "establish a robust causal coverage effect"))
    row = next(row for row in payload["sources"] if row["output_path"] == derived.relative_to(tmp_path).as_posix())
    row["output_sha256"] = hashlib.sha256(derived.read_bytes()).hexdigest()
    receipt.write_text(json.dumps(payload))
    assert any("source-bound caption projection" in issue for issue in projection.validate_print_projection(tmp_path))


def test_mixed_populations_do_not_deny_actual_within_population_connections(tmp_path):
    from server.services.paper_presentation_caption import _risk_caption
    from server.services.paper_trusted_plot_source import match_trusted_plot
    from server.tests.test_paper_plot_semantics_projection import _csv

    source, rows = _risk(tmp_path, population=True, repeated=True)
    rows[0]["dataset"] = "Dataset B"
    _csv(tmp_path, rows)
    caption = _risk_caption(tmp_path, match_trusted_plot(source)[1])
    assert "same dataset and method" in caption and "different datasets are not joined" in caption
    assert "do not establish a within-dataset coverage effect" not in caption


@pytest.mark.parametrize("generated", [False, True])
def test_external_evidence_caption_uses_explicit_status_without_inventing_generation(tmp_path, generated):
    from server.services.paper_presentation_caption import _risk_caption
    from server.services.paper_trusted_plot_source import match_trusted_plot
    from server.tests.test_paper_plot_semantics_projection import _csv

    source, rows = _risk(tmp_path)
    for row in rows:
        row['status'] = 'synthetic_preview' if generated else 'executed'
    relative = _csv(tmp_path, rows)
    target = tmp_path / 'external.csv'
    target.write_bytes((tmp_path / relative).read_bytes())
    parameters = {**match_trusted_plot(source)[1], 'data_path': 'external.csv'}
    before = target.read_bytes()
    caption = _risk_caption(tmp_path, parameters)
    assert ('generated scenario labels' in caption) == generated
    assert ('population confidence intervals' in caption) == generated
    assert ('supplied bounds' in caption) != generated
    assert target.read_bytes() == before
