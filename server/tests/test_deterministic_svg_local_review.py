"""Deterministic rich SVGs use hash-bound local evidence, not model review."""

from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path

from server.services.rich_svg_backend import (
    _finish_rendered_candidate, generate_rich_svg,
)
from server.services.figure_generation_transaction import reusable_result
from server.services.figure_models import FigureType
from server.services.rich_svg_visual_review import (
    LOCAL_PROTOCOL, local_review_issues, local_review_record,
)


def _metadata() -> dict:
    return {
        "production_strategy": "deterministic_template",
        "producer_kind": "deterministic",
        "skill_invocation_verified": True,
        "skill_invocation_verified_by": "deterministic-runtime-figure-builder",
        "producer_input_sha256": "typed-input-v1",
        "scientific_role": "evaluation_design",
        "scientific_question": "How is the method evaluated?",
        "element_mappings": [{"element_id": "cohort", "source_path": "contract.json"}],
    }


def _files(root: Path) -> tuple[Path, Path, Path, str]:
    directory = root / "figures" / "diagrams"
    directory.mkdir(parents=True)
    svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1000 500"><g id="cohort"><text x="40" y="60">Cohort</text></g></svg>\n'
    source = directory / "evaluation_design.svg"
    pdf = directory / "evaluation_design.pdf"
    png = directory / "evaluation_design.png"
    source.write_text(svg, encoding="utf-8")
    pdf.write_bytes(b"%PDF-1.4\nsynthetic local test")
    png.write_bytes(b"synthetic PNG bytes")
    return source, pdf, png, svg


def _passing_round(source: Path, png: Path) -> dict:
    return {
        "status": "passed",
        "content_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "render_sha256": hashlib.sha256(png.read_bytes()).hexdigest(),
    }


def test_local_review_binds_all_variants_and_scientific_brief(tmp_path: Path) -> None:
    source, pdf, png, _svg = _files(tmp_path)
    metadata = {**_metadata(), "visual_review_rounds": [_passing_round(source, png)]}
    record = local_review_record(metadata, source, pdf, png)
    assert record["protocol"] == LOCAL_PROTOCOL
    assert local_review_issues(
        {**metadata, "deterministic_visual_review": record}, source, pdf, png,
    ) == []
    for path, label in (
        (source, "editable SVG"), (pdf, "rendered PDF"), (png, "rendered PNG"),
    ):
        original = path.read_bytes()
        path.write_bytes(original + b"changed")
        assert f"stale for the {label}" in "; ".join(local_review_issues(
            {**metadata, "deterministic_visual_review": record}, source, pdf, png,
        ))
        path.write_bytes(original)
    changed = {**metadata, "scientific_question": "A changed scientific question"}
    assert "stale for the scientific brief" in "; ".join(local_review_issues(
        {**changed, "deterministic_visual_review": record}, source, pdf, png,
    ))
    assert "cannot claim independent native-image review" in "; ".join(local_review_issues(
        {**metadata, "deterministic_visual_review": record,
         "independent_visual_review": {"protocol": "native-image-v1"}},
        source, pdf, png,
    ))
    assert "lacks a passing round" in "; ".join(local_review_issues(
        {**metadata, "visual_review_rounds": [],
         "deterministic_visual_review": record}, source, pdf, png,
    ))


def test_runtime_template_never_invokes_native_reviewer(
    tmp_path: Path, monkeypatch,
) -> None:
    source, pdf, png, svg = _files(tmp_path)
    metadata = _metadata()
    rounds: list[dict] = []

    async def forbidden_review(**_kwargs):
        raise AssertionError("deterministic template must not call model API")

    monkeypatch.setattr(
        "server.services.rich_svg_visual_review.review_candidate", forbidden_review,
    )

    class Registry:
        @staticmethod
        def raster_visual_quality_issues(_path: Path) -> list[str]:
            return []

        @staticmethod
        def rich_svg_render_issues(_path: Path) -> list[str]:
            return []

    def append_review(_path: Path, record: dict) -> list[dict]:
        rounds.append(record)
        return rounds

    result = asyncio.run(_finish_rendered_candidate(
        registry=Registry(), root_path=tmp_path, artifact_stem="evaluation_design",
        source=source, pdf=pdf, png=png, svg=svg, value=metadata,
        mappings=metadata["element_mappings"], ids={"cohort"},
        review=tmp_path / "review.json", append_review=append_review,
        sha256_path=lambda path: hashlib.sha256(path.read_bytes()).hexdigest(),
    ))
    assert result.success
    assert result.metadata["independent_visual_review"] == {}
    assert result.metadata["deterministic_visual_review"]["protocol"] == LOCAL_PROTOCOL
    assert rounds[-1]["status"] == "passed"
    assert not (tmp_path / ".merak" / "figure-candidates").exists()


def test_unverified_template_cannot_enter_local_review(tmp_path: Path) -> None:
    source, _pdf, _png, svg = _files(tmp_path)
    result = asyncio.run(generate_rich_svg(
        svg, str(source.parent), "evaluation_design",
        {**_metadata(), "skill_invocation_verified": False},
        normalize_svg=lambda value: value,
        convert_variants=lambda *_args: (True, ""),
        append_review=lambda *_args: [],
        sha256_path=lambda path: hashlib.sha256(path.read_bytes()).hexdigest(),
    ))
    assert not result.success
    assert "verified runtime producer provenance" in result.error


def test_reuse_requires_current_local_evidence(tmp_path: Path) -> None:
    source, pdf, png, _svg = _files(tmp_path)
    metadata = {
        **_metadata(), "content_sha256": "unchanged-svg-identity",
        "rendered_variants": {"png": str(png)},
        "visual_review_rounds": [_passing_round(source, png)],
    }
    metadata["deterministic_visual_review"] = local_review_record(
        metadata, source, pdf, png,
    )

    class Registry:
        def __init__(self) -> None:
            self.commits = 0

        @staticmethod
        def _is_manuscript_asset(_metadata: dict) -> bool:
            return True

        @staticmethod
        def find_reusable(*_args, **_kwargs) -> dict:
            return {
                "type": "rich_svg", "source_path": str(source),
                "output_path": str(pdf), "metadata": metadata,
            }

        @staticmethod
        def project_root(_output_dir: str) -> Path:
            return tmp_path

        def record(self, **_kwargs) -> tuple[Path, dict]:
            self.commits += 1
            return tmp_path / "manifest.json", {}

    registry = Registry()
    reused = reusable_result(
        registry, str(source.parent), "evaluation_design", FigureType.RICH_SVG,
        "Evaluation design", dict(metadata),
    )
    assert reused is not None and reused.success and registry.commits == 1
    png.write_bytes(b"changed pixels")
    assert reusable_result(
        registry, str(source.parent), "evaluation_design", FigureType.RICH_SVG,
        "Evaluation design", dict(metadata),
    ) is None
    assert registry.commits == 1
