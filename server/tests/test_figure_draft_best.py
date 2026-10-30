"""Unaccepted SVG revisions cannot replace a stronger staged composition."""

import json
from pathlib import Path

from server.services.figure_draft_best import (
    matching_best_draft,
    preserve_best_draft,
    restore_best_after_local_failure,
)
from server.agent.tools.figure_draft_tools import begin_figure_svg_draft


def _write_draft(root: Path, content: str) -> tuple[Path, Path]:
    parts = root / "parts"
    parts.mkdir(parents=True, exist_ok=True)
    (parts / "000_open.svgfrag").write_text("<svg>", encoding="utf-8")
    (parts / "001_mechanism.svgfrag").write_text(content, encoding="utf-8")
    source = root / "method_architecture.svg"
    source.write_text("<svg>" + content + "</svg>", encoding="utf-8")
    (root / "manifest.json").write_text(json.dumps({
        "schema": 1, "artifact_name": "method_architecture",
        "parts": ["000_open.svgfrag", "001_mechanism.svgfrag"],
    }), encoding="utf-8")
    return root, source


def test_lower_scoring_revision_restores_best_fragments(tmp_path: Path) -> None:
    directory, source = _write_draft(tmp_path / "draft", "<g>best</g>")
    regressed, score = preserve_best_draft(
        directory, source, {"score": 7.2, "verdict": "refine"},
        ["minor issue"], "a" * 64,
    )
    assert regressed is False and score == 7.2

    (directory / "parts" / "001_mechanism.svgfrag").write_text(
        "<g>worse</g>", encoding="utf-8",
    )
    source.write_text("<svg><g>worse</g></svg>", encoding="utf-8")
    regressed, score = preserve_best_draft(
        directory, source, {"score": 5.0, "verdict": "refine"},
        ["major issue"], "a" * 64,
    )
    assert regressed is True and score == 7.2
    assert "best" in source.read_text(encoding="utf-8")
    assert "best" in (
        directory / "parts" / "001_mechanism.svgfrag"
    ).read_text(encoding="utf-8")


def test_fewer_scientific_blockers_beat_higher_unaccepted_score(
    tmp_path: Path,
) -> None:
    directory, source = _write_draft(tmp_path / "draft", "<g>old</g>")
    previous = {
        "score": 7.8, "verdict": "refine",
        "findings": [{"severity": "blocker", "message": value}
                     for value in ("wrong input", "wrong output", "wrong gate")],
    }
    preserve_best_draft(directory, source, previous, ["three defects"], "a" * 64)
    source.write_text("<svg><g>safer</g></svg>", encoding="utf-8")
    candidate = {
        "score": 7.0, "verdict": "refine",
        "findings": [{"severity": "blocker", "message": "wrong gate"}],
    }
    regressed, score = preserve_best_draft(
        directory, source, candidate, ["one defect"], "a" * 64,
    )
    assert regressed is False and score == 7.0
    assert matching_best_draft(directory, "a" * 64)["score"] == 7.0


def test_old_review_policy_snapshot_cannot_restore_staged_svg(tmp_path: Path) -> None:
    directory, source = _write_draft(tmp_path / "draft", "<g>old</g>")
    preserve_best_draft(
        directory, source, {"score": 7.8, "verdict": "refine"},
        ["old issue"], "a" * 64,
    )
    best_path = directory / "best-composition" / "best.json"
    best = json.loads(best_path.read_text(encoding="utf-8"))
    best["review_policy_version"] = 1
    best_path.write_text(json.dumps(best), encoding="utf-8")
    source.write_text("<svg><g>new</g></svg>", encoding="utf-8")
    assert restore_best_after_local_failure(directory, "a" * 64) == {}
    assert "new" in source.read_text(encoding="utf-8")


def test_best_composition_survives_new_delegate_begin_and_restores_contract(
    tmp_path: Path,
) -> None:
    directory = tmp_path / ".merak" / "figure-drafts" / "method_architecture"
    directory, source = _write_draft(directory, "<g>strongest</g>")
    (directory / "canvas-layout.json").write_text(
        '{"schema":12,"identity":"best-layout"}', encoding="utf-8",
    )
    (directory / "mechanism-ir.json").write_text(
        '{"schema":2,"identity":"best-contract"}', encoding="utf-8",
    )
    preserve_best_draft(
        directory, source,
        {"score": 7.4, "verdict": "refine",
         "checklist": {"readable_hierarchy": False},
         "improvement_prompt": "Make the shared route legible.",
         "findings": [{
            "target_layer": "runtime", "target_ids": ["composition"],
            "severity": "blocker", "message": "Tighten the branch route.",
            "repair_action": "Repair the deterministic connector.",
        }]},
        ["Tighten the branch route."], "b" * 64,
    )

    begin_figure_svg_draft(
        "method_architecture", '<svg xmlns="http://www.w3.org/2000/svg">',
        str(tmp_path),
    )

    assert (directory / "best-composition" / "best.json").is_file()
    saved = json.loads((directory / "best-composition" / "best.json").read_text(
        encoding="utf-8",
    ))
    assert saved["checklist"] == {"readable_hierarchy": False}
    assert saved["improvement_prompt"] == "Make the shared route legible."
    assert not source.is_file()
    directory, source = _write_draft(directory, "<g>regression</g>")
    (directory / "canvas-layout.json").write_text(
        '{"schema":12,"identity":"worse-layout"}', encoding="utf-8",
    )
    (directory / "mechanism-ir.json").write_text(
        '{"schema":2,"identity":"worse-contract"}', encoding="utf-8",
    )
    regressed, score = preserve_best_draft(
        directory, source, {"score": 6.2, "verdict": "refine"},
        ["More severe issue."], "b" * 64,
    )

    assert regressed is True and score == 7.4
    assert "strongest" in source.read_text(encoding="utf-8")
    assert "best-layout" in (
        directory / "canvas-layout.json"
    ).read_text(encoding="utf-8")
    assert "best-contract" in (
        directory / "mechanism-ir.json"
    ).read_text(encoding="utf-8")


def test_equal_scoring_changed_candidate_restores_existing_best(tmp_path: Path) -> None:
    directory, source = _write_draft(tmp_path / "draft", "<g>best</g>")
    preserve_best_draft(
        directory, source, {"score": 7.2, "verdict": "refine"},
        ["one issue"], "c" * 64,
    )
    source.write_text("<svg><g>different but not better</g></svg>", encoding="utf-8")
    (directory / "parts" / "001_mechanism.svgfrag").write_text(
        "<g>different but not better</g>", encoding="utf-8",
    )

    regressed, _score = preserve_best_draft(
        directory, source, {"score": 7.2, "verdict": "refine"},
        ["one issue"], "c" * 64,
    )

    assert regressed is True
    assert "best" in source.read_text(encoding="utf-8")


def test_best_survives_blueprint_and_mapping_revision_with_same_source_brief(
    tmp_path: Path,
) -> None:
    directory, source = _write_draft(tmp_path / "draft", "<g>best</g>")
    manifest_path = directory / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest.update({
        "source_bundle_sha256": "source-one",
        "figure_spec_sha256": "spec-one",
        "visual_blueprint_sha256": "blueprint-one",
        "element_mappings_sha256": "mapping-one",
    })
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    preserve_best_draft(
        directory, source, {"score": 7.8, "verdict": "refine"},
        ["clarify conditional branch"], "blueprint-one",
    )

    source.write_text("<svg><g>colliding revision</g></svg>", encoding="utf-8")
    manifest.update({
        "visual_blueprint_sha256": "blueprint-two",
        "element_mappings_sha256": "mapping-two",
    })
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    assert matching_best_draft(directory, "blueprint-two")["score"] == 7.8
    best = restore_best_after_local_failure(directory, "blueprint-two")
    assert best["score"] == 7.8
    assert "best" in source.read_text(encoding="utf-8")
    restored = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert restored["visual_blueprint_sha256"] == "blueprint-one"
    assert restored["element_mappings_sha256"] == "mapping-one"


def test_best_cannot_cross_changed_source_brief(tmp_path: Path) -> None:
    directory, source = _write_draft(tmp_path / "draft", "<g>old</g>")
    manifest_path = directory / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["figure_spec_sha256"] = "spec-one"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    preserve_best_draft(
        directory, source, {"score": 7.8, "verdict": "refine"},
        ["old issue"], "blueprint-one",
    )
    source.write_text("<svg><g>new contract</g></svg>", encoding="utf-8")
    manifest["figure_spec_sha256"] = "spec-two"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    assert restore_best_after_local_failure(directory, "blueprint-two") == {}
    assert "new contract" in source.read_text(encoding="utf-8")


def test_corrupt_best_snapshot_cannot_replace_valid_revision(tmp_path: Path) -> None:
    directory, source = _write_draft(tmp_path / "draft", "<g>old-best</g>")
    preserve_best_draft(
        directory, source, {"score": 7.8, "verdict": "refine"},
        ["minor issue"], "blueprint-one",
    )
    (directory / "best-composition" / source.name).write_text(
        "<svg>interrupted snapshot</svg>", encoding="utf-8",
    )
    source.write_text("<svg><g>valid new candidate</g></svg>", encoding="utf-8")
    regressed, score = preserve_best_draft(
        directory, source, {"score": 7.0, "verdict": "refine"},
        ["current repair"], "blueprint-one",
    )
    assert regressed is False and score == 7.0
    assert "valid new candidate" in source.read_text(encoding="utf-8")
    assert matching_best_draft(directory, "blueprint-one")["score"] == 7.0
