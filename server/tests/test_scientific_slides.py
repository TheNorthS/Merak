from __future__ import annotations

import hashlib
import json
from pathlib import Path
import pytest

from server.services.node_risk_audit import node_risk_audit_service
from server.services.scientific_slides import (
    scientific_slide_service,
)
from server.services.slide_figures import required_synthetic_figure_ids
from server.services.simulation_policy import (
    SIMULATION_MANIFEST_SCHEMA,
    simulation_manifest_contract_issues,
)
from server.workflows.engine import WorkflowEngine, WorkflowRun


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_complete_synthetic_bundle(root: Path) -> dict[str, Path]:
    from server.tests._scientific_slide_fixture import write_current_slide_bundle

    outputs = write_current_slide_bundle(root)
    selected = set(required_synthetic_figure_ids(root))
    path = root / "figures/FIGURE_MANIFEST.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    for entry in manifest["figures"]:
        entry["paper_ready"] = entry["id"] in selected
        entry["metadata"]["paper_selected"] = entry["id"] in selected
    _write_json(path, manifest)
    return outputs


def test_slide_fallback_is_contract_grounded_and_uses_selected_figures(tmp_path: Path) -> None:
    _write_json(tmp_path / "ideas" / "SELECTED_IDEA.json", {
        "title": "Catalyst Stability Under Thermal Cycling",
        "problem_statement": "Catalyst grains coarsen during thermal cycling.",
        "hypothesis": "Surface treatment slows coarsening.",
        "claims": [{"id": "C1", "statement": "The treatment lowers coarsening rate."}],
        "mechanisms": [{
            "id": "M1",
            "name": "Surface-energy modulation",
            "description": "Changes the coarsening pathway.",
            "required": True,
        }],
        "falsification_conditions": ["Untreated control has the same coarsening rate."],
    })
    _write_json(tmp_path / "experiments" / "METHOD_CONTRACT.json", {
        "evaluation_contract": {
            "comparators_or_controls": ["untreated catalyst"],
            "component_tests": ["remove surface treatment"],
        },
    })
    _write_json(tmp_path / "figures" / "SCIENTIFIC_ASSET_PLAN.json", {
        "evidence_mode": "planned",
    })
    from PIL import Image, ImageDraw
    method_output = tmp_path / "figures/diagrams/method_architecture.png"
    method_output.parent.mkdir(parents=True)
    image = Image.new("RGB", (800, 450), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((100, 120, 260, 260), fill="#198099")
    draw.rectangle((440, 120, 600, 260), fill="#c65d21")
    image.save(method_output)
    _write_json(tmp_path / "figures" / "FIGURE_MANIFEST.json", {
        "figures": [
            {
                "id": "method_architecture",
                "paper_ready": True,
                "output_path": "figures/diagrams/method_architecture.png",
                "output_sha256": _sha256(method_output),
                "metadata": {
                    "scientific_role": "method",
                    "paper_selected": True,
                    "scientific_question": "How does M1 implement the hypothesis?",
                },
            },
            {
                "id": "falsification_design",
                "paper_ready": True,
                "output_path": "figures/diagrams/falsification_design.png",
                "metadata": {
                    "scientific_role": "protocol",
                    "paper_selected": True,
                    "scientific_question": "Which result would reject C1?",
                },
            },
            {
                "id": "workflow_status",
                "paper_ready": True,
                "output_path": "figures/workflow.png",
                "metadata": {"scientific_role": "analysis", "paper_selected": False},
            },
        ],
    })

    result = scientific_slide_service.ensure(tmp_path, "materials")
    tex = (tmp_path / "slides" / "main.tex").read_text(encoding="utf-8")

    assert result["generated"] is True
    assert "Catalyst Stability Under Thermal Cycling" in tex
    assert "Surface-energy modulation" in tex
    assert "method_architecture.png" in tex
    assert "falsification_design.png" not in tex
    assert "workflow.png" not in tex
    assert tex.count(r"\begin{frame}") >= 10
    assert "C1" not in tex
    assert "M1" not in tex
    assert "outperforms" not in tex
    plan = json.loads((tmp_path / "slides" / "SLIDE_PLAN.json").read_text(encoding="utf-8"))
    assert plan["selected_figures"] == ["method_architecture"]


def test_existing_slide_source_is_not_overwritten(tmp_path: Path) -> None:
    main = tmp_path / "slides" / "main.tex"
    main.parent.mkdir(parents=True)
    main.write_text("researcher slides\n", encoding="utf-8")

    result = scientific_slide_service.ensure(tmp_path, "test")

    assert result["generated"] is False
    assert main.read_text(encoding="utf-8") == "researcher slides\n"


def test_platform_authored_slide_source_is_bound_without_overwrite(
    tmp_path: Path,
) -> None:
    main = tmp_path / "slides" / "main.tex"
    main.parent.mkdir(parents=True)
    source = "\\documentclass{beamer}\\begin{document}Deck\\end{document}\n"
    main.write_text(source, encoding="utf-8")
    _write_json(
        tmp_path / "figures" / "SCIENTIFIC_ASSET_PLAN.json",
        {"evidence_mode": "synthetic_preview"},
    )

    result = scientific_slide_service.ensure(
        tmp_path,
        "test",
        bind_existing=True,
    )

    assert result["generated"] is False
    assert result["bound"] is True
    assert main.read_text(encoding="utf-8") == source
    plan = json.loads(
        (tmp_path / "slides" / "SLIDE_PLAN.json").read_text(
            encoding="utf-8"
        )
    )
    assert plan["generator"] == "model:paper-talk"
    assert plan["platform_managed"] is True
    assert plan["evidence_mode"] == "synthetic_preview"
    assert plan["source_bundle_sha256"]
    assert plan["tex_sha256"] == hashlib.sha256(main.read_bytes()).hexdigest()


def test_forced_slide_repair_backs_up_existing_source(tmp_path: Path) -> None:
    main = tmp_path / "slides" / "main.tex"
    main.parent.mkdir(parents=True)
    main.write_text("broken researcher slides\n", encoding="utf-8")
    _write_json(tmp_path / "ideas" / "SELECTED_IDEA.json", {
        "title": "Repairable Research Deck",
        "claims": [{"id": "C1", "statement": "A pending claim."}],
        "mechanisms": [],
    })
    _write_json(tmp_path / "experiments" / "METHOD_CONTRACT.json", {})
    _write_json(tmp_path / "figures" / "SCIENTIFIC_ASSET_PLAN.json", {"evidence_mode": "planned"})
    _write_json(tmp_path / "figures" / "FIGURE_MANIFEST.json", {"figures": []})

    result = scientific_slide_service.ensure(tmp_path, "test", force=True)

    assert result["generated"] is True
    assert main.read_text(encoding="utf-8").startswith("% MERAK_GENERATED_SLIDES")
    backups = list((tmp_path / "slides" / "revisions").glob("previous_slides_*.tex"))
    assert len(backups) == 1
    assert backups[0].read_text(encoding="utf-8") == "broken researcher slides\n"


def test_generated_slides_refresh_when_the_upstream_bundle_changes(
    tmp_path: Path,
) -> None:
    selected = tmp_path / "ideas" / "SELECTED_IDEA.json"
    _write_json(selected, {
        "title": "Initial Research Title",
        "claims": [{"id": "C1", "statement": "A pending claim."}],
        "mechanisms": [],
    })
    _write_json(tmp_path / "experiments" / "METHOD_CONTRACT.json", {})
    _write_json(
        tmp_path / "figures" / "SCIENTIFIC_ASSET_PLAN.json",
        {"evidence_mode": "planned"},
    )
    _write_json(tmp_path / "figures" / "FIGURE_MANIFEST.json", {"figures": []})

    first = scientific_slide_service.ensure(tmp_path, "test")
    first_plan = json.loads(
        (tmp_path / "slides" / "SLIDE_PLAN.json").read_text(encoding="utf-8")
    )
    _write_json(selected, {
        "title": "Revised Research Title",
        "claims": [{"id": "C1", "statement": "A pending claim."}],
        "mechanisms": [],
    })

    second = scientific_slide_service.ensure(tmp_path, "test")
    second_plan = json.loads(
        (tmp_path / "slides" / "SLIDE_PLAN.json").read_text(encoding="utf-8")
    )
    tex = (tmp_path / "slides" / "main.tex").read_text(encoding="utf-8")

    assert first["generated"] is True
    assert second["generated"] is True
    assert "Revised Research Title" in tex
    assert (
        first_plan["source_bundle_sha256"]
        != second_plan["source_bundle_sha256"]
    )


def test_slide_plan_binding_refreshes_after_deterministic_tex_repair(
    tmp_path: Path,
) -> None:
    selected = tmp_path / "ideas" / "SELECTED_IDEA.json"
    _write_json(selected, {
        "title": "Source-bound Deck",
        "claims": [{"id": "C1", "statement": "A pending claim."}],
        "mechanisms": [],
    })
    _write_json(tmp_path / "experiments" / "METHOD_CONTRACT.json", {})
    _write_json(
        tmp_path / "figures" / "SCIENTIFIC_ASSET_PLAN.json",
        {"evidence_mode": "planned"},
    )
    _write_json(tmp_path / "figures" / "FIGURE_MANIFEST.json", {"figures": []})
    scientific_slide_service.ensure(tmp_path, "test")
    main = tmp_path / "slides" / "main.tex"
    plan_path = tmp_path / "slides" / "SLIDE_PLAN.json"
    main.write_text(
        main.read_text(encoding="utf-8") + "\n% deterministic package repair\n",
        encoding="utf-8",
    )

    assert scientific_slide_service.refresh_plan_binding(tmp_path) is True
    refreshed = json.loads(plan_path.read_text(encoding="utf-8"))
    assert refreshed["tex_sha256"] == hashlib.sha256(main.read_bytes()).hexdigest()
    assert refreshed["binding_refreshed_at"] > refreshed["generated_at"]


def test_slide_plan_binding_refreshes_actual_figure_selection(
    tmp_path: Path,
) -> None:
    figure = tmp_path / "figures" / "result.pdf"
    figure.parent.mkdir(parents=True, exist_ok=True)
    figure.write_bytes(b"%PDF-1.4\nqualified result figure")
    _write_json(
        tmp_path / "figures" / "SCIENTIFIC_ASSET_PLAN.json",
        {"evidence_mode": "executed"},
    )
    _write_json(tmp_path / "figures" / "FIGURE_MANIFEST.json", {
        "figures": [{
            "id": "primary_result",
            "paper_ready": True,
            "output_path": "figures/result.pdf",
            "output_sha256": _sha256(figure),
            "metadata": {
                "semantic_key": "primary_result",
                "scientific_role": "result",
                "evidence_status": "executed",
                "paper_selected": True,
            },
        }],
    })
    main = tmp_path / "slides" / "main.tex"
    main.parent.mkdir(parents=True, exist_ok=True)
    main.write_text(
        "\\documentclass{beamer}\\begin{document}Deck\\end{document}\n",
        encoding="utf-8",
    )
    scientific_slide_service.bind_existing(tmp_path)
    plan_path = tmp_path / "slides" / "SLIDE_PLAN.json"
    assert json.loads(plan_path.read_text(encoding="utf-8"))[
        "selected_figures"
    ] == []

    main.write_text(
        "\\documentclass{beamer}\\usepackage{graphicx}"
        "\\begin{document}\\includegraphics{../figures/result.pdf}"
        "\\end{document}\n",
        encoding="utf-8",
    )

    assert scientific_slide_service.refresh_plan_binding(tmp_path) is True
    refreshed = json.loads(plan_path.read_text(encoding="utf-8"))
    assert refreshed["selected_figures"] == ["primary_result"]
    assert refreshed["tex_sha256"] == _sha256(main)


def test_executed_ppt_audit_requires_available_scientific_figures(
    tmp_path: Path,
) -> None:
    method_figure = tmp_path / "figures" / "method.pdf"
    result_figure = tmp_path / "figures" / "result.pdf"
    method_figure.parent.mkdir(parents=True, exist_ok=True)
    method_figure.write_bytes(b"%PDF-1.4\nqualified method figure")
    result_figure.write_bytes(b"%PDF-1.4\nqualified result figure")
    _write_json(
        tmp_path / "figures" / "SCIENTIFIC_ASSET_PLAN.json",
        {"evidence_mode": "executed"},
    )
    _write_json(tmp_path / "figures" / "FIGURE_MANIFEST.json", {
        "figures": [
            {
                "id": "method_architecture",
                "paper_ready": True,
                "output_path": "figures/method.pdf",
                "output_sha256": _sha256(method_figure),
                "metadata": {
                    "semantic_key": "method_architecture",
                    "scientific_role": "method",
                    "evidence_status": "executed",
                    "paper_selected": True,
                },
            },
            {
                "id": "primary_result",
                "paper_ready": True,
                "output_path": "figures/result.pdf",
                "output_sha256": _sha256(result_figure),
                "metadata": {
                    "semantic_key": "primary_result",
                    "scientific_role": "result",
                    "evidence_status": "executed",
                    "paper_selected": True,
                },
            },
        ],
    })
    main = tmp_path / "slides" / "main.tex"
    main.parent.mkdir(parents=True, exist_ok=True)
    frames = "".join(
        f"\\begin{{frame}}{{S{index}}}Evidence\\end{{frame}}"
        for index in range(6)
    )
    main.write_text(
        "\\documentclass{beamer}\\begin{document}"
        + frames
        + "\\end{document}",
        encoding="utf-8",
    )
    scientific_slide_service.bind_existing(tmp_path)

    findings = node_risk_audit_service._audit_ppt(
        tmp_path,
        {"run_experiment": True},
    )
    figure_findings = {
        item["id"]: item
        for item in findings
        if item["id"].startswith("PPT-FIG-")
    }

    assert "PPT-FIG-003" in figure_findings
    assert "any qualified scientific figure" in figure_findings[
        "PPT-FIG-003"
    ]["message"]


def test_slide_plan_binding_does_not_mask_upstream_source_drift(
    tmp_path: Path,
) -> None:
    selected = tmp_path / "ideas" / "SELECTED_IDEA.json"
    _write_json(selected, {
        "title": "Initial Deck",
        "claims": [{"id": "C1", "statement": "A pending claim."}],
        "mechanisms": [],
    })
    _write_json(tmp_path / "experiments" / "METHOD_CONTRACT.json", {})
    _write_json(
        tmp_path / "figures" / "SCIENTIFIC_ASSET_PLAN.json",
        {"evidence_mode": "planned"},
    )
    _write_json(tmp_path / "figures" / "FIGURE_MANIFEST.json", {"figures": []})
    scientific_slide_service.ensure(tmp_path, "test")
    plan_path = tmp_path / "slides" / "SLIDE_PLAN.json"
    original = json.loads(plan_path.read_text(encoding="utf-8"))
    _write_json(selected, {
        "title": "Changed Upstream Research",
        "claims": [{"id": "C1", "statement": "A changed pending claim."}],
        "mechanisms": [],
    })

    assert scientific_slide_service.refresh_plan_binding(tmp_path) is False
    unchanged = json.loads(plan_path.read_text(encoding="utf-8"))
    assert unchanged["source_bundle_sha256"] == original["source_bundle_sha256"]
    assert "binding_refreshed_at" not in unchanged


def test_synthetic_fallback_uses_contribution_figures_and_preserves_complete_bundle(
    tmp_path: Path,
) -> None:
    outputs = _write_complete_synthetic_bundle(tmp_path)
    payload = json.loads(outputs["simulation_manifest"].read_text(encoding="utf-8"))
    assert payload["schema"] == SIMULATION_MANIFEST_SCHEMA
    assert simulation_manifest_contract_issues(payload) == []
    assert len(scientific_slide_service.qualified_synthetic_figures(tmp_path)) == 4
    assert len(payload["figure_files"]) == 7

    result = scientific_slide_service.ensure(tmp_path, "benchmark")
    tex = (tmp_path / "slides" / "main.tex").read_text(encoding="utf-8")
    plan = json.loads(
        (tmp_path / "slides" / "SLIDE_PLAN.json").read_text(encoding="utf-8")
    )

    assert result["generated"] is True
    assert 10 <= tex.count(r"\begin{frame}") <= 20
    for figure_id in required_synthetic_figure_ids(tmp_path):
        relative = outputs[figure_id].relative_to(tmp_path).as_posix()
        assert f"../{relative}" in tex
    assert plan["selected_figures"] == list(
        required_synthetic_figure_ids(tmp_path)
    )
    assert "Without measured results" not in tex
    assert "Execute the frozen primary comparison" not in tex
    assert "registered benchmark" in tex
    assert "NOT FOR SUBMISSION" not in tex
    assert "synthetic preview" not in tex.casefold()
    assert "watermark" not in tex.casefold()


def test_synthetic_slide_binding_includes_outputs_and_rejects_figure_drift(
    tmp_path: Path,
) -> None:
    outputs = _write_complete_synthetic_bundle(tmp_path)
    scientific_slide_service.ensure(tmp_path, "benchmark")
    plan_path = tmp_path / "slides" / "SLIDE_PLAN.json"
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    bound_sources = set(plan["sources"])

    for figure_id in required_synthetic_figure_ids(tmp_path):
        assert outputs[figure_id].relative_to(tmp_path).as_posix() in bound_sources
    changed = outputs["synthetic_preview_main_comparison"]
    changed.write_bytes(changed.read_bytes() + b"\n% changed after binding")

    assert scientific_slide_service.refresh_plan_binding(tmp_path) is False
    unchanged = json.loads(plan_path.read_text(encoding="utf-8"))
    assert unchanged["source_bundle_sha256"] == plan["source_bundle_sha256"]
    assert "binding_refreshed_at" not in unchanged


def test_platform_synthetic_deck_binds_all_referenced_qualified_figures(
    tmp_path: Path,
) -> None:
    outputs = _write_complete_synthetic_bundle(tmp_path)
    assert len(scientific_slide_service.qualified_synthetic_figures(tmp_path)) == 4
    main = tmp_path / "slides" / "main.tex"
    main.parent.mkdir(parents=True, exist_ok=True)
    graphics = "\n".join(
        "\\includegraphics{" + "../"
        + outputs[figure_id].relative_to(tmp_path).as_posix()
        + "}"
        for figure_id in required_synthetic_figure_ids(tmp_path)
    )
    source = (
        "\\documentclass{beamer}\n"
        "\\begin{document}\n"
        "\\begin{frame}{Registered benchmark}\n"
        f"{graphics}\n"
        "\\end{frame}\n"
        "\\end{document}\n"
    )
    main.write_text(source, encoding="utf-8")

    result = scientific_slide_service.ensure(
        tmp_path,
        "benchmark",
        bind_existing=True,
    )
    plan = json.loads(
        (tmp_path / "slides" / "SLIDE_PLAN.json").read_text(encoding="utf-8")
    )

    assert result["bound"] is True
    assert plan["selected_figures"] == list(
        required_synthetic_figure_ids(tmp_path)
    )
    assert plan["tex_sha256"] == _sha256(main)


def test_platform_synthetic_deck_binds_hash_identical_staged_figures(
    tmp_path: Path,
) -> None:
    outputs = _write_complete_synthetic_bundle(tmp_path)
    assert len(scientific_slide_service.qualified_synthetic_figures(tmp_path)) == 4
    slides = tmp_path / "slides"
    slides.mkdir(parents=True, exist_ok=True)
    graphics: list[str] = []
    for figure_id in required_synthetic_figure_ids(tmp_path):
        canonical = outputs[figure_id]
        staged = slides / canonical.name
        staged.write_bytes(canonical.read_bytes())
        graphics.append(r"\includegraphics{" + staged.name + "}")
    main = slides / "main.tex"
    main.write_text(
        "\\documentclass{beamer}\n\\begin{document}\n"
        "\\begin{frame}{Results}\n" + "\n".join(graphics)
        + "\n\\end{frame}\n\\end{document}\n",
        encoding="utf-8",
    )

    scientific_slide_service.bind_existing(tmp_path)
    plan = json.loads((slides / "SLIDE_PLAN.json").read_text(encoding="utf-8"))
    assert plan["selected_figures"] == list(
        required_synthetic_figure_ids(tmp_path)
    )


def test_synthetic_ppt_audit_accepts_bounded_findings_without_pending_marker(
    tmp_path: Path,
) -> None:
    _write_complete_synthetic_bundle(tmp_path)
    scientific_slide_service.ensure(tmp_path, "benchmark")

    findings = node_risk_audit_service._audit_ppt(
        tmp_path,
        {
            "run_experiment": False,
            "non_experiment_evidence_mode": "synthetic_preview",
        },
    )
    ids = {item["id"] for item in findings}

    assert "PPT-CLAIM-001" not in ids
    assert "PPT-MODE-001" not in ids
    assert "PPT-SIM-001" not in ids
    assert "PPT-SIM-002" not in ids
    assert "PPT-SIM-003" not in ids


def test_synthetic_ppt_audit_rejects_unbound_result_figure(
    tmp_path: Path,
) -> None:
    _write_complete_synthetic_bundle(tmp_path)
    manifest_path = tmp_path / "figures" / "FIGURE_MANIFEST.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    main_comparison = next(
        item
        for item in manifest["figures"]
        if item["id"] == "synthetic_preview_main_comparison"
    )
    main_comparison["metadata"]["simulation_manifest_sha256"] = "0" * 64
    _write_json(manifest_path, manifest)
    scientific_slide_service.ensure(tmp_path, "benchmark")

    findings = node_risk_audit_service._audit_ppt(
        tmp_path,
        {
            "run_experiment": False,
            "non_experiment_evidence_mode": "synthetic_preview",
        },
    )

    assert any(
        item["id"] == "PPT-SIM-001"
        and "synthetic_preview_main_comparison" in item["message"]
        for item in findings
    )


@pytest.mark.parametrize("defect", ["missing_output", "missing_hash", "stale_hash"])
def test_standard_slide_selection_rejects_missing_or_unbound_outputs(tmp_path: Path, defect: str) -> None:
    figure = tmp_path / "figures/method.png"
    figure.parent.mkdir()
    from PIL import Image
    Image.new("RGB", (100, 100), "white").save(figure)
    entry = {"id": "method", "paper_ready": True, "output_path": "figures/method.png",
             "output_sha256": _sha256(figure), "metadata": {"scientific_role": "method", "paper_selected": True}}
    if defect == "missing_output":
        figure.unlink()
    elif defect == "missing_hash":
        entry.pop("output_sha256")
    else:
        entry["output_sha256"] = "0" * 64
    assert scientific_slide_service.qualified_standard_figures(tmp_path, {"figures": [entry]}) == []


def test_old_simulation_slide_schema_is_rejected_without_migration(tmp_path: Path) -> None:
    outputs = _write_complete_synthetic_bundle(tmp_path)
    path = outputs["simulation_manifest"]
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["schema"] = 5
    _write_json(path, payload)
    before = path.read_bytes()
    assert any("older than" in issue for issue in simulation_manifest_contract_issues(payload))
    assert scientific_slide_service.qualified_synthetic_figures(tmp_path) == []
    assert path.read_bytes() == before


def test_current_slide_fixture_is_local_binding_data_not_workflow_acceptance(tmp_path: Path) -> None:
    outputs = _write_complete_synthetic_bundle(tmp_path)
    payload = json.loads(outputs["simulation_manifest"].read_text(encoding="utf-8"))
    assert payload["fixture_only"] is True
    assert not (tmp_path / ".merak").exists()
    assert "run_id" not in payload and "workflow_status" not in payload
    for record in payload["figure_files"]:
        import fitz
        with fitz.open(tmp_path / record["outputs"]["pdf"]) as document:
            assert document.page_count == 1
            assert "Local asset binding fixture" in document[0].get_text()
        assert _sha256(tmp_path / record["source"]) == record["source_sha256"]
        assert all(_sha256(tmp_path / relative) == record["output_sha256"][kind]
                   for kind, relative in record["outputs"].items())


def test_synthetic_ppt_prompt_uses_complete_qualified_result_figures(
    tmp_path: Path,
) -> None:
    _write_complete_synthetic_bundle(tmp_path)
    run = WorkflowRun(
        id="synthetic-ppt-prompt",
        project_path=str(tmp_path),
        options={
            "run_experiment": False,
            "non_experiment_evidence_mode": "synthetic_preview",
        },
    )

    prompt = WorkflowEngine()._input_ppt("benchmark", {}, run)

    assert "当前证据模式: synthetic_preview" in prompt
    assert "不机械纳入七图" in prompt
    assert all(identity in prompt for identity in required_synthetic_figure_ids(tmp_path))
    assert "synthetic_preview_training_dynamics" not in prompt
    assert "paper_ready=true" in prompt
    assert "SIMULATION_MANIFEST" in prompt
    assert "尚无真实实验或 claim pending" in prompt
    assert "submission_eligible=false" in prompt
    assert "警告框或水印" in prompt
