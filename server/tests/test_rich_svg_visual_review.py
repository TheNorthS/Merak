"""Local regression tests for native-image review and best-candidate ownership."""

from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path

from server.services.api_visual_review_invocation import ApiVisualReview
from server.services.figure_generation_transaction import reusable_result
from server.services.figure_models import FigureType
from server.services.rich_svg_visual_review import (
    PROTOCOL, commit_best_candidate, native_review_issues, review_candidate,
    review_gate_issues,
)


def _accepted(score: float = 8.6) -> dict:
    return {
        "score": score, "verdict": "accept", "issues": [], "findings": [],
        "strengths": ["Scientific mechanism is legible"],
        "improvement_prompt": "",
        "checklist": {
            key: True for key in (
                "five_second_comprehension", "scientific_mechanism_clarity",
                "domain_specific_visual_encoding", "focal_hierarchy",
                "causal_flow", "balanced_composition", "label_economy",
                "paper_scale_readability", "no_generic_card_wall",
                "no_visual_artifacts",
            )
        },
    }


def _files(root: Path, suffix: str) -> tuple[Path, Path, Path, str]:
    directory = root / "figures" / "diagrams"
    directory.mkdir(parents=True, exist_ok=True)
    source, pdf, png = (directory / f"method_architecture{extension}" for extension in (".svg", ".pdf", ".png"))
    source.write_text(f'<svg xmlns="http://www.w3.org/2000/svg"><text>{suffix}</text></svg>', encoding="utf-8")
    pdf.write_bytes(b"%PDF-1.4\n" + suffix.encode())
    png.write_bytes(b"PNG " + suffix.encode())
    return source, pdf, png, hashlib.sha256(source.read_bytes()).hexdigest()


def _trace(root: Path, png: Path, identity: str) -> Path:
    trace = root / ".merak" / "model-api-reviewer" / f"rich-svg-{identity}"
    trace.mkdir(parents=True)
    (trace / "meta.json").write_text(json.dumps({
        "success": True, "invocation_id": f"model-api:{identity}",
        "model_identity": "reviewer-model", "image_attachment_mode": "api-native-image-content",
        "image_sha256": {png.relative_to(root).as_posix(): hashlib.sha256(png.read_bytes()).hexdigest()},
    }), encoding="utf-8")
    return trace


def test_acceptance_is_hash_bound_and_best_updates_only_after_commit(
    tmp_path: Path, monkeypatch,
) -> None:
    source, pdf, png, digest = _files(tmp_path, "first")
    trace = _trace(tmp_path, png, "first")

    async def fake_review(**kwargs):
        assert kwargs["image_path"] == png
        assert "five seconds" in kwargs["prompt"]
        return ApiVisualReview(json.dumps(_accepted()), "model-api:first", "reviewer-model", "test", str(trace))

    monkeypatch.setattr(
        "server.services.api_visual_reviewer.api_visual_reviewer.review_rich_svg", fake_review,
    )
    review, issues = asyncio.run(review_candidate(
        root=tmp_path, artifact_id="method_architecture", metadata={},
        source=source, pdf=pdf, png=png, source_sha256=digest,
    ))
    assert not issues
    archive = Path(review["candidate_path"])
    assert (archive / "method_architecture.svg").read_bytes() == source.read_bytes()
    assert not (archive.parent / "best.json").exists()
    assert native_review_issues({"independent_visual_review": review}, tmp_path, source, png) == []
    commit_best_candidate(tmp_path, "method_architecture", review)
    assert json.loads((archive.parent / "best.json").read_text())["candidate_sha256"] == digest
    repeated, repeated_issues = asyncio.run(review_candidate(
        root=tmp_path, artifact_id="method_architecture", metadata={},
        source=source, pdf=pdf, png=png, source_sha256=digest,
    ))
    assert not repeated_issues
    assert repeated["candidate_path"] != review["candidate_path"]
    assert json.loads((archive / "review.json").read_text())["review"]["score"] == 8.6
    png.write_bytes(b"changed pixels")
    assert "native-image review is stale for the rendered PNG" in native_review_issues(
        {"independent_visual_review": review}, tmp_path, source, png,
    )


def test_accepted_polish_notes_become_nonblocking_advisories(
    tmp_path: Path, monkeypatch,
) -> None:
    source, pdf, png, digest = _files(tmp_path, "advisory")
    trace = _trace(tmp_path, png, "advisory")
    payload = _accepted(8.3)
    payload["issues"] = ["Tighten optional whitespace in the final panel"]
    payload["findings"] = [{
        "target_layer": "runtime", "target_ids": ["composition"],
        "severity": "advisory",
        "message": payload["issues"][0],
        "repair_action": "Tighten the optional whitespace.",
    }]

    async def fake_review(**_kwargs):
        return ApiVisualReview(
            json.dumps(payload), "model-api:advisory", "reviewer-model",
            "test", str(trace),
        )

    monkeypatch.setattr(
        "server.services.api_visual_reviewer.api_visual_reviewer.review_rich_svg",
        fake_review,
    )
    review, issues = asyncio.run(review_candidate(
        root=tmp_path, artifact_id="method_architecture", metadata={},
        source=source, pdf=pdf, png=png, source_sha256=digest,
    ))
    assert issues == []
    assert review["issues"] == []
    assert review["advisories"] == [
        "Tighten optional whitespace in the final panel",
    ]


def test_lower_scored_accepted_candidate_is_archived_but_does_not_replace_best(
    tmp_path: Path, monkeypatch,
) -> None:
    first_source, first_pdf, first_png, first_digest = _files(tmp_path, "first")
    trace = _trace(tmp_path, first_png, "first")

    async def fake_review(**kwargs):
        return ApiVisualReview(json.dumps(_accepted(8.7)), "model-api:first", "reviewer-model", "test", str(trace))

    monkeypatch.setattr(
        "server.services.api_visual_reviewer.api_visual_reviewer.review_rich_svg", fake_review,
    )
    first, issues = asyncio.run(review_candidate(
        root=tmp_path, artifact_id="method_architecture", metadata={},
        source=first_source, pdf=first_pdf, png=first_png, source_sha256=first_digest,
    ))
    assert not issues
    commit_best_candidate(tmp_path, "method_architecture", first)
    source, pdf, png, digest = _files(tmp_path, "second")
    trace = _trace(tmp_path, png, "second")

    async def lower_review(**kwargs):
        return ApiVisualReview(json.dumps(_accepted(8.5)), "model-api:second", "reviewer-model", "test", str(trace))

    monkeypatch.setattr(
        "server.services.api_visual_reviewer.api_visual_reviewer.review_rich_svg", lower_review,
    )
    second, issues = asyncio.run(review_candidate(
        root=tmp_path, artifact_id="method_architecture", metadata={},
        source=source, pdf=pdf, png=png, source_sha256=digest,
    ))
    assert issues == []
    assert (Path(second["candidate_path"]) / "method_architecture.png").is_file()
    best = json.loads((Path(first["candidate_path"]).parent / "best.json").read_text())
    assert best["candidate_sha256"] == first_digest
    assert not native_review_issues({"independent_visual_review": second}, tmp_path, source, png)


def test_scientific_checks_block_but_soft_checks_and_score_do_not() -> None:
    review = _accepted(7.8)
    review["checklist"]["balanced_composition"] = False
    review["checklist"]["label_economy"] = False
    review["findings"] = [{
        "target_layer": "runtime", "target_ids": ["composition"],
        "severity": "advisory", "message": "Tighten whitespace",
        "repair_action": "Reduce excess whitespace",
    }]
    assert review_gate_issues(review) == []

    review["checklist"]["causal_flow"] = False
    assert "native-image scientific or legibility checklist failed" in review_gate_issues(review)
    review["checklist"]["causal_flow"] = True
    review["findings"][0]["severity"] = "blocker"
    assert "native-image figure has blocking findings" in review_gate_issues(review)


def test_accepted_verdict_cannot_hide_unstructured_or_blocking_issue() -> None:
    review = _accepted(9.0)
    review["issues"] = ["The decision arrow has no terminal"]
    assert "native-image issues lack structured severity" in review_gate_issues(review)
    review["findings"] = [{
        "target_layer": "runtime", "target_ids": ["composition"],
        "severity": "blocker", "message": review["issues"][0],
        "repair_action": "Connect the decision arrow to its terminal",
    }]
    assert "native-image figure has blocking findings" in review_gate_issues(review)


def test_legacy_rich_svg_cannot_satisfy_native_review(tmp_path: Path) -> None:
    source, _pdf, png, _digest = _files(tmp_path, "legacy")
    assert native_review_issues({}, tmp_path, source, png) == [
        "native-image figure review is missing or uses a retired protocol"
    ]
    assert PROTOCOL == "native-image-v1"


def test_old_review_policy_is_not_silently_promoted(tmp_path: Path) -> None:
    source, _pdf, png, digest = _files(tmp_path, "old-policy")
    review = {
        **_accepted(7.8), "protocol": PROTOCOL,
        "source_sha256": digest,
    }
    issues = native_review_issues(
        {"independent_visual_review": review}, tmp_path, source, png,
    )
    assert "native-image review policy is stale" in issues


def test_reviewer_failure_archives_candidate_without_best_pointer(
    tmp_path: Path, monkeypatch,
) -> None:
    source, pdf, png, digest = _files(tmp_path, "unavailable")

    async def unavailable(**kwargs):
        raise TimeoutError("review model unavailable")

    monkeypatch.setattr(
        "server.services.api_visual_reviewer.api_visual_reviewer.review_rich_svg", unavailable,
    )
    async def no_delay(_seconds):
        return None

    monkeypatch.setattr("server.services.rich_svg_visual_review.asyncio.sleep", no_delay)
    review, issues = asyncio.run(review_candidate(
        root=tmp_path, artifact_id="method_architecture", metadata={},
        source=source, pdf=pdf, png=png, source_sha256=digest,
    ))
    assert "TimeoutError" in issues[0]
    archive = Path(review["candidate_path"])
    assert (archive / "method_architecture.svg").is_file()
    assert not (archive.parent / "best.json").exists()


def test_transient_reviewer_failure_retries_the_same_candidate(
    tmp_path: Path, monkeypatch,
) -> None:
    source, pdf, png, digest = _files(tmp_path, "retry")
    trace = _trace(tmp_path, png, "retry")
    calls = 0

    async def transient(**kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("OpenAI API error 502")
        return ApiVisualReview(json.dumps(_accepted()), "model-api:retry", "reviewer-model", "test", str(trace))

    async def no_delay(_seconds):
        return None

    monkeypatch.setattr(
        "server.services.api_visual_reviewer.api_visual_reviewer.review_rich_svg", transient,
    )
    monkeypatch.setattr("server.services.rich_svg_visual_review.asyncio.sleep", no_delay)
    review, issues = asyncio.run(review_candidate(
        root=tmp_path, artifact_id="method_architecture", metadata={},
        source=source, pdf=pdf, png=png, source_sha256=digest,
    ))
    assert calls == 2
    assert not issues
    assert len([path for path in Path(review["candidate_path"]).parent.iterdir() if path.is_dir()]) == 1


def test_changed_scientific_brief_does_not_compare_against_obsolete_best(
    tmp_path: Path, monkeypatch,
) -> None:
    source, pdf, png, digest = _files(tmp_path, "old")
    trace = _trace(tmp_path, png, "old")

    async def old_review(**kwargs):
        return ApiVisualReview(json.dumps(_accepted(9.0)), "model-api:old", "reviewer-model", "test", str(trace))

    monkeypatch.setattr(
        "server.services.api_visual_reviewer.api_visual_reviewer.review_rich_svg", old_review,
    )
    first, issues = asyncio.run(review_candidate(
        root=tmp_path, artifact_id="method_architecture",
        metadata={"scientific_question": "How does A work?"},
        source=source, pdf=pdf, png=png, source_sha256=digest,
    ))
    assert not issues
    commit_best_candidate(tmp_path, "method_architecture", first)
    source, pdf, png, digest = _files(tmp_path, "new")
    trace = _trace(tmp_path, png, "new")

    async def new_review(**kwargs):
        return ApiVisualReview(json.dumps(_accepted(8.1)), "model-api:new", "reviewer-model", "test", str(trace))

    monkeypatch.setattr(
        "server.services.api_visual_reviewer.api_visual_reviewer.review_rich_svg", new_review,
    )
    second, issues = asyncio.run(review_candidate(
        root=tmp_path, artifact_id="method_architecture",
        metadata={"scientific_question": "How does B work?"},
        source=source, pdf=pdf, png=png, source_sha256=digest,
    ))
    assert not issues
    assert second["brief_sha256"] != first["brief_sha256"]


def test_reuse_cannot_launder_an_old_review_into_a_new_scientific_brief(
    tmp_path: Path, monkeypatch,
) -> None:
    source, pdf, png, digest = _files(tmp_path, "old")
    trace = _trace(tmp_path, png, "old")

    async def old_review(**kwargs):
        return ApiVisualReview(json.dumps(_accepted()), "model-api:old", "reviewer-model", "test", str(trace))

    monkeypatch.setattr(
        "server.services.api_visual_reviewer.api_visual_reviewer.review_rich_svg", old_review,
    )
    review, issues = asyncio.run(review_candidate(
        root=tmp_path, artifact_id="method_architecture",
        metadata={"scientific_question": "Old mechanism"},
        source=source, pdf=pdf, png=png, source_sha256=digest,
    ))
    assert not issues

    class Registry:
        def _is_manuscript_asset(self, metadata):
            return True

        def find_reusable(self, *args, **kwargs):
            return {
                "source_path": str(source), "output_path": str(pdf),
                "metadata": {
                    "scientific_question": "Old mechanism",
                    "independent_visual_review": review,
                    "rendered_variants": {"png": str(png)},
                },
            }

        def project_root(self, output_dir):
            return tmp_path

        def record(self, **kwargs):
            raise AssertionError("Stale review must not be reused")

    assert reusable_result(
        Registry(), str(source.parent), "method_architecture", FigureType.RICH_SVG,
        "New method", {"content_sha256": "same", "scientific_question": "New mechanism"},
    ) is None
