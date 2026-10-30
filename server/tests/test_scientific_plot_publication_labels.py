"""Canonical quantitative plots retain authored labels in actual SVG text."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import matplotlib
import pytest

from server.services.figure_artifacts import figure_artifact_registry
from server.services.scientific_plotting import build_scientific_plot_script


def _asset(raw_metric: str, display: str) -> dict:
    return {
        "metric": raw_metric,
        "data_path": "experiments/results/aggregate.csv",
        "recommended_plot_type": "interval_comparison",
        "publication_labels": [{
            "schema": 1, "id": "comparison.metric", "kind": "metric",
            "display_text": display,
        }],
    }


@pytest.mark.parametrize("raw_metric,display", [
    ("accuracy", "Accuracy"),
    ("macro_f1", "Macro-F1"),
    ("hazard_ratio", "Overall survival (hazard ratio)"),
])
def test_rendered_svg_uses_authored_metric_and_preserves_bound_csv(
    tmp_path: Path, raw_metric: str, display: str,
) -> None:
    data = tmp_path / "experiments/results/aggregate.csv"
    data.parent.mkdir(parents=True)
    data.write_text(
        "method,metric,mean,ci95_low,ci95_high,n\n"
        f"Matched baseline,{raw_metric},0.61,0.60,0.62,3\n"
        f"Proposed method,{raw_metric},0.68,0.67,0.69,3\n",
        encoding="utf-8",
    )
    original = data.read_bytes()
    source = tmp_path / "figures/generated/comparison.py"
    source.parent.mkdir(parents=True)
    script = build_scientific_plot_script(_asset(raw_metric, display), {})
    source.write_text(script, encoding="utf-8")
    svg = source.with_suffix(".svg")
    with matplotlib.rc_context():
        namespace = {"__file__": str(source)}
        exec(compile(script, str(source), "exec"), namespace)
        namespace["fig"].savefig(svg, bbox_inches="tight")
        assert namespace["ax"].get_xlabel() == display
        namespace["plt"].close(namespace["fig"])
    item = {"metadata": {
        "rendered_variants": {"svg": svg.relative_to(tmp_path).as_posix()},
        "rendered_variant_sha256": {"svg": hashlib.sha256(svg.read_bytes()).hexdigest()},
    }}
    visible = figure_artifact_registry._publication_semantic_text(item, tmp_path, source)
    assert display in visible
    if "_" in raw_metric:
        assert raw_metric not in visible
    assert data.read_bytes() == original
    item["metadata"]["rendered_variant_sha256"]["svg"] = "0" * 64
    assert figure_artifact_registry._publication_semantic_text(item, tmp_path, source) == ""


def test_plot_builder_rejects_missing_or_ambiguous_public_metric() -> None:
    asset = _asset("macro_f1", "Macro-F1")
    asset.pop("publication_labels")
    with pytest.raises(ValueError, match="publication_labels"):
        build_scientific_plot_script(asset, {})
    asset = _asset("macro_f1", "Macro-F1")
    asset["publication_labels"].append({
        "schema": 1, "id": "comparison.other", "kind": "metric",
        "display_text": "Accuracy",
    })
    with pytest.raises(ValueError, match="exactly one authored metric"):
        build_scientific_plot_script(asset, {})


def test_wrapped_plot_labels_have_real_line_breaks() -> None:
    script = build_scientific_plot_script(_asset("accuracy", "Accuracy"), {})
    assert 'return "\\n".join(textwrap.wrap' in script
    assert 'return "\\\\n".join(textwrap.wrap' not in script


def _transaction_project(root: Path) -> tuple[dict, Path]:
    asset = _asset("macro_f1", "Macro-F1")
    data = root / asset["data_path"]
    data.parent.mkdir(parents=True)
    data.write_text(
        "method,mean,ci95_low,ci95_high,n\n"
        "Matched baseline,0.61,0.60,0.62,3\n"
        "Proposed method,0.68,0.67,0.69,3\n", encoding="utf-8",
    )
    selected = root / "ideas/SELECTED_IDEA.json"
    selected.parent.mkdir()
    selected.write_text(json.dumps({"claims": [{"id": "C1"}]}), encoding="utf-8")
    asset.update({
        "id": "main_comparison", "scientific_role": "result",
        "source_data": [asset["data_path"]], "claim_ids": ["C1"],
        "evidence_status": "executed", "producer_kind": "deterministic",
        "production_strategy": "deterministic_plot", "manuscript_eligible": True,
        "generator_skill": "deterministic-figure-plot", "skill": "deterministic-figure-plot",
    })
    return asset, data


@pytest.mark.asyncio
@pytest.mark.parametrize("tamper_after_binding", [False, True])
async def test_actual_plot_transaction_prebinds_variants_before_alignment(
    tmp_path: Path, monkeypatch, tamper_after_binding: bool,
) -> None:
    from server.services.figure_engine import figure_engine
    from server.services.figure_models import FigureType
    from server.services import figure_scientific_alignment as alignment

    asset, data = _transaction_project(tmp_path)
    original_data = data.read_bytes()
    actual_check = alignment.candidate_scientific_alignment_issues
    observed = []

    def inspect_candidate(registry, root, metadata, source):
        variant = root / metadata["rendered_variants"]["svg"]
        assert metadata["rendered_variant_sha256"]["svg"] == hashlib.sha256(variant.read_bytes()).hexdigest()
        observed.append(True)
        if tamper_after_binding:
            variant.write_text(variant.read_text(encoding="utf-8") + "\n<!-- changed -->", encoding="utf-8")
        return actual_check(registry, root, metadata, source)

    monkeypatch.setattr(alignment, "candidate_scientific_alignment_issues", inspect_candidate)
    result = await figure_engine.generate(
        description="Matched comparison", artifact_name="main_comparison",
        figure_type=FigureType.MATPLOTLIB, output_dir=str(tmp_path / "figures/plots"),
        code=build_scientific_plot_script(asset, {}), metadata=asset,
    )
    assert observed == [True]
    assert result.success is (not tamper_after_binding), result.error
    assert data.read_bytes() == original_data
    if tamper_after_binding:
        assert "scientific alignment" in result.error
        assert not (tmp_path / "figures/plots/main_comparison.svg").exists()
        assert not (tmp_path / "figures/FIGURE_MANIFEST.json").exists()
    else:
        assert result.manifest_path
        assert "Macro-F1" in figure_artifact_registry._publication_semantic_text(
            {"metadata": result.metadata}, tmp_path, Path(result.source_path),
        )
