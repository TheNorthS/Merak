"""Producer-specific provenance checks for reviewed rich SVG figures."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path

import pytest

from server.services.figure_scientific_quality import (
    _metadata_issues,
    _rich_svg_issues,
)
from server.services.rich_svg_visual_review import local_review_record


class _CleanRegistry:
    @staticmethod
    def rich_svg_source_issues(_source: Path) -> list[str]:
        return []

    @staticmethod
    def raster_visual_quality_issues(_preview: Path) -> list[str]:
        return []

    @staticmethod
    def rich_svg_render_issues(_preview: Path) -> list[str]:
        return []


def _hash(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _metadata(source: Path, preview: Path, *, deterministic: bool) -> dict:
    strategy = "deterministic_template" if deterministic else "model_composed_full_svg"
    skill = "deterministic-figure-template" if deterministic else "model-svg-figure"
    metadata = {
        "production_strategy": strategy,
        "producer_kind": "deterministic" if deterministic else "model",
        "generator": (
            "deterministic-runtime-rich-svg" if deterministic
            else "model-authored-rich-svg"
        ),
        "renderer": "rich-svg-vector-v1",
        "render_status": "rendered",
        "source_faithful": (
            "runtime-template-svg-same-source-variants" if deterministic
            else "model-authored-svg-same-source-variants"
        ),
        "model_authored": not deterministic,
        "model_authored_blueprint": not deterministic,
        "scientific_svg_compiler": (
            "deterministic-runtime-template-v1" if deterministic
            else "model-authored-svg-v1"
        ),
        "skill": skill,
        "generator_skill": skill,
        "skill_invocation_verified": True,
        "skill_invocation_verified_by": (
            "deterministic-runtime-figure-builder" if deterministic
            else "agent-runtime"
        ),
        "rendered_variants": {
            "svg": str(source), "pdf": str(source.with_suffix(".pdf")),
            "png": str(preview),
        },
        "element_mappings": [
            {"element_id": f"stage_{index}", "source_path": source.name}
            for index in range(4)
        ],
        "visual_review_rounds": [{
            "status": "passed", "content_sha256": _hash(source),
            "render_sha256": _hash(preview),
        }],
    }
    if deterministic:
        metadata["deterministic_visual_review"] = local_review_record(
            metadata, source, source.with_suffix(".pdf"), preview,
        )
    return metadata


@pytest.fixture
def figure_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    source = tmp_path / "figure.svg"
    preview = tmp_path / "figure.png"
    source.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg">'
        + "".join(f'<g id="stage_{index}"/>' for index in range(4))
        + "</svg>"
    )
    preview.write_bytes(b"reviewed preview pixels")
    source.with_suffix(".pdf").write_bytes(b"%PDF-1.4\nreviewed-pdf")
    monkeypatch.setattr(
        "server.services.rich_svg_visual_review.native_review_issues",
        lambda *_args: [],
    )
    return source, preview


@pytest.mark.parametrize("deterministic", [True, False])
def test_rich_svg_accepts_only_matching_producer_provenance(
    figure_files: tuple[Path, Path], deterministic: bool,
) -> None:
    source, preview = figure_files
    metadata = _metadata(source, preview, deterministic=deterministic)

    assert _rich_svg_issues(
        _CleanRegistry(), "evaluation_design", metadata,
        source.parent, source, "evaluation_design",
    ) == []


def test_legacy_model_svg_keeps_its_original_provenance_contract(
    figure_files: tuple[Path, Path],
) -> None:
    source, preview = figure_files
    metadata = _metadata(source, preview, deterministic=False)
    metadata.pop("production_strategy")
    metadata.pop("skill_invocation_verified_by")
    metadata.pop("generator_skill")
    metadata.pop("skill_invocation_verified")
    metadata.pop("source_faithful")
    metadata.pop("render_status")
    metadata.pop("model_authored")
    metadata["skill"] = "rich-svg-figure"

    assert _rich_svg_issues(
        _CleanRegistry(), "method_overview", metadata,
        source.parent, source, "evaluation_design",
    ) == []


@pytest.mark.parametrize("deterministic", [True, False])
def test_rich_svg_rejects_cross_producer_and_forged_runtime_metadata(
    figure_files: tuple[Path, Path], deterministic: bool,
) -> None:
    source, preview = figure_files
    metadata = _metadata(source, preview, deterministic=deterministic)
    metadata["producer_kind"] = "model" if deterministic else "deterministic"
    metadata["generator"] = (
        "model-authored-rich-svg" if deterministic else "deterministic-runtime-rich-svg"
    )
    metadata["skill_invocation_verified_by"] = "unverified-caller"

    issues = _rich_svg_issues(
        _CleanRegistry(), "evaluation_design", metadata,
        source.parent, source, "evaluation_design",
    )

    assert any("requires producer_kind" in issue for issue in issues)
    assert any("generator provenance" in issue for issue in issues)
    assert any("skill_invocation_verified_by provenance" in issue for issue in issues)


def test_local_review_failure_is_not_bypassed_for_runtime_template(
    figure_files: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, preview = figure_files
    metadata = _metadata(source, preview, deterministic=True)
    monkeypatch.setattr(
        "server.services.rich_svg_visual_review.local_review_issues",
        lambda *_args: ["deterministic local-pixel review rejected the candidate"],
    )

    issues = _rich_svg_issues(
        _CleanRegistry(), "evaluation_design", metadata,
        source.parent, source, "evaluation_design",
    )

    assert any("deterministic local-pixel review rejected" in issue for issue in issues)


def test_evaluation_mapping_tamper_does_not_pass_provenance_gate(
    figure_files: tuple[Path, Path],
) -> None:
    source, preview = figure_files
    metadata = _metadata(source, preview, deterministic=True)
    metadata["element_mappings"][0]["source_path"] = "missing-contract.json"

    issues = _rich_svg_issues(
        _CleanRegistry(), "evaluation_design", metadata,
        source.parent, source, "evaluation_design",
    )

    assert any("element mapping 1 source is missing" in issue for issue in issues)


@pytest.mark.parametrize("deterministic", [True, False])
def test_rich_svg_review_remains_bound_to_source_and_render(
    figure_files: tuple[Path, Path], deterministic: bool,
) -> None:
    source, preview = figure_files
    metadata = _metadata(source, preview, deterministic=deterministic)
    source.write_text(source.read_text() + "\n<!-- changed after review -->")
    preview.write_bytes(b"different preview pixels")

    issues = _rich_svg_issues(
        _CleanRegistry(), "evaluation_design", metadata,
        source.parent, source, "evaluation_design",
    )

    assert any("visual review is stale for editable source" in issue for issue in issues)
    assert any("visual review is stale for rendered preview" in issue for issue in issues)


def test_source_data_must_still_exist_for_rich_svg(figure_files: tuple[Path, Path]) -> None:
    source, _preview = figure_files
    metadata = {
        "scientific_role": "evaluation_design",
        "style_profile": "merak-publication-v1",
        "scientific_question": "How is evaluation locked?",
        "intended_comparison": "Method versus control",
        "visual_encoding": "Study protocol flow",
        "source_data": [source.name],
    }
    item = {"caption": "An explicit source-bound evaluation protocol figure."}
    assert _metadata_issues("evaluation_design", item, metadata, source.parent) == []

    source.unlink()
    assert any(
        "source_data is missing or empty" in issue
        for issue in _metadata_issues("evaluation_design", item, metadata, source.parent)
    )


def test_source_scoped_mapping_floor_matches_scene_size(
    figure_files: tuple[Path, Path],
) -> None:
    source, preview = figure_files
    source.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg">'
        '<g id="input"/><g id="method"/></svg>',
        encoding="utf-8",
    )
    metadata = _metadata(source, preview, deterministic=False)
    metadata["scientific_scene"] = {
        "objects": [{"id": "input"}, {"id": "method"}],
    }
    metadata["element_mappings"] = [
        {"element_id": "input", "source_path": source.name},
        {"element_id": "method", "source_path": source.name},
    ]
    assert _rich_svg_issues(
        _CleanRegistry(), "method_architecture", metadata,
        source.parent, source, "method",
    ) == []
