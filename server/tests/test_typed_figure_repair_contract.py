"""Pure regression checks for typed labels and producer-owned figure repair."""

import json
from pathlib import Path

import pytest

from server.services.artifact_contract import artifact_write_error
from server.services.figure_file_transaction import FigureFileTransaction
from server.services.figure_producer_policy import figure_producers
from server.services.figure_scientific_alignment import _visible_source_issues
from server.services.figure_svg_sources import _evaluation_design_svg
from server.services.publication_figure_labels import (
    concept_labels,
    validate_publication_labels,
)
from server.workflows.revision_progress_diagnostics import (
    revision_stall_classification,
    revision_stall_message,
)
from server.workflows.figure_repair_routing import rebuild_deterministic_assets
from server.workflows.engine import WorkflowEngine
from server.workflows.models import WorkflowRun
from server.services.figure_engine import FigureType, figure_engine
from server.services.figure_models import FigureResult
from server.services.deterministic_figure_builder import ensure_evaluation_design


def _math_label(label_id: str, text: str, latex: str) -> dict:
    return {
        "schema": 1, "id": label_id, "kind": "math",
        "display_text": text, "display_math": latex,
    }


def _evaluation_brief(**overrides: object) -> dict:
    brief = {
        "mechanism_nodes": [{"publication_name": "Predictive encoder"}],
        "study_conditions": ["remove prediction objective"],
        "evaluation_contract": {
            "primary_outcomes": ["held-out accuracy"],
            "comparators_or_controls": ["matched baseline"],
        },
        "evaluation_protocol": {"primary_split": "external_test", "analysis_unit": "subject"},
    }
    return {**brief, **overrides}


def test_svg_math_label_is_not_confused_with_source_code() -> None:
    labels = [_math_label("method.context", "zctx", r"z_{\mathrm{ctx}}")]
    raw = '<svg><text data-label-id="method.context" data-label-kind="math">z<tspan>ctx</tspan></text></svg>'
    assert _visible_source_issues(
        "method_architecture", "method", "zctx", raw_source=raw,
        publication_labels=labels,
    ) == []


def test_undeclared_snake_case_and_task_logits_remain_code_findings() -> None:
    issues = _visible_source_issues(
        "method_architecture", "method", "z_ctx task_logits",
        raw_source="<svg><text>z_ctx task_logits</text></svg>",
        publication_labels=[{"schema": 1, "id": "method.name", "kind": "concept", "display_text": "Context representation"}],
    )
    assert any("task_logits" in issue and "z_ctx" in issue for issue in issues)


def test_bare_number_cannot_be_a_required_publication_label() -> None:
    _, issues = validate_publication_labels([{
        "schema": 1, "id": "evaluation.weight", "kind": "metric",
        "display_text": "1.0",
    }])
    assert any("bare number" in issue for issue in issues)


def test_deterministic_evaluation_renderer_consumes_typed_labels() -> None:
    labels = concept_labels(
        ["multiclass classification", "macro F1", "task loss weight 1.0"],
        namespace="evaluation.term", limit=3,
    )
    svg, _ = _evaluation_design_svg({
        "publication_labels": labels,
        "method_brief": _evaluation_brief(tasks=["multiclass classification"]),
    })
    assert "multiclass" in svg and "classification" in svg
    assert all(value in svg for value in ("task loss", "weight 1.0"))
    assert 'data-label-id="evaluation.term.1"' in svg


def test_deterministic_evaluation_defaults_are_domain_neutral() -> None:
    svg, mappings = _evaluation_design_svg({
        "method_brief": _evaluation_brief(
            mechanism_nodes=[{"id": "M1", "publication_name": "Predictive residual encoder"}],
            study_conditions=["remove encoder component"],
            evaluation_contract={
                "primary_outcomes": ["held-out accuracy"],
                "comparators_or_controls": ["matched baseline"],
                "focal_condition": "Predictive residual encoder",
                "primary_comparator": "matched baseline",
            },
        ),
    })
    assert "Predictive residual encoder" in svg
    assert "remove encoder component" in svg
    assert "external test" in svg
    assert "M1 removed" not in svg
    assert 'data-label-id="evaluation.term.1"' in svg
    assert "montage" not in svg.casefold()
    assert {item["element_id"] for item in mappings} >= {
        "eval_removed_condition", "eval_locked_perturbation",
    }


@pytest.mark.asyncio
async def test_deterministic_evaluation_svg_does_not_require_model_blueprint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    for relative in (
        "experiments/src/data.py",
        "experiments/src/data_contract.py",
        "experiments/src/evaluation.py",
        "experiments/EXPERIMENT_PLAN.md",
        "experiments/METHOD_CONTRACT.json",
        "experiments/results/analysis.md",
    ):
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("source-bound fixture\n", encoding="utf-8")
    labels = concept_labels(
        ["held-out accuracy", "calibration risk", "stress retention"],
        namespace="evaluation.term", limit=3,
    )
    svg, mappings = _evaluation_design_svg({
        "publication_labels": labels,
        "method_brief": _evaluation_brief(tasks=["EEG montage transfer"]),
    })

    async def accept_candidate(**kwargs):
        return {
            "protocol": "native-image-v1", "verdict": "accept", "score": 9.0,
            "source_sha256": kwargs["source_sha256"],
        }, []

    monkeypatch.setattr(
        "server.services.rich_svg_visual_review.review_candidate",
        accept_candidate,
    )
    result = await figure_engine._generate_rich_svg(
        svg,
        output_dir=str(tmp_path / "figures" / "diagrams"),
        artifact_stem="evaluation_design",
        metadata={
            "scientific_role": "evaluation_design",
            "producer_kind": "deterministic",
            "production_strategy": "deterministic_template",
            "skill_invocation_verified": True,
            "skill_invocation_verified_by": "deterministic-runtime-figure-builder",
            "generator_skill": "deterministic-figure-template",
            "element_mappings": mappings,
            "publication_labels": labels,
        },
    )

    assert result.success, result.error
    assert result.metadata["generator"] == "deterministic-runtime-rich-svg"
    assert result.metadata["model_authored"] is False
    assert result.metadata["model_authored_blueprint"] is False
    assert result.metadata["scientific_svg_compiler"] == (
        "deterministic-runtime-template-v1"
    )


@pytest.mark.asyncio
async def test_deterministic_evaluation_template_commits_through_public_engine(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    ideas = tmp_path / "ideas"
    figures = tmp_path / "figures"
    ideas.mkdir()
    figures.mkdir()
    selected = {
        "schema": 2,
        "status": "accepted",
        "publication": {"title": "Leakage-safe held-out evaluation"},
        "problem_statement": "Separate development from held-out evaluation.",
        "hypothesis": "A locked protocol prevents evaluation leakage.",
        "claims": [{"id": "C1", "publication_statement": "Evaluation is locked."}],
        "mechanisms": [],
    }
    (ideas / "SELECTED_IDEA.json").write_text(
        json.dumps(selected), encoding="utf-8",
    )
    source_paths = (
        "experiments/src/data.py",
        "experiments/src/data_contract.py",
        "experiments/src/evaluation.py",
        "experiments/EXPERIMENT_PLAN.md",
        "experiments/METHOD_CONTRACT.json",
        "experiments/results/analysis.md",
    )
    for relative in source_paths:
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("source-bound fixture\n", encoding="utf-8")
    labels = concept_labels(
        ["held-out accuracy", "calibration risk", "stress retention"],
        namespace="evaluation.term", limit=3,
    )
    spec = {
        "id": "evaluation_design", "kind": "figure",
        "scientific_role": "evaluation_design", "claim_ids": ["C1"],
        "publication_labels": labels,
        "scientific_question": "How is evaluation isolated?",
        "producer_kind": "deterministic",
        "production_strategy": "deterministic_template",
        "recommended_backend": "rich_svg",
        "source_data": list(source_paths),
    }
    (figures / "FIGURE_SPECS.json").write_text(
        json.dumps({"schema": 4, "figures": [spec]}), encoding="utf-8",
    )
    svg, mappings = _evaluation_design_svg({
        **spec, "method_brief": _evaluation_brief(tasks=["EEG montage transfer"]),
    })

    async def accept_candidate(**kwargs):
        return {
            "protocol": "native-image-v1", "verdict": "accept", "score": 9.0,
            "source_sha256": kwargs["source_sha256"],
        }, []

    monkeypatch.setattr(
        "server.services.rich_svg_visual_review.review_candidate",
        accept_candidate,
    )
    monkeypatch.setattr(
        "server.services.rich_svg_visual_review.native_review_issues",
        lambda *_args, **_kwargs: [],
    )
    monkeypatch.setattr(
        "server.services.rich_svg_visual_review.commit_best_candidate",
        lambda *_args, **_kwargs: None,
    )
    result = await figure_engine.generate(
        description="Leakage-safe held-out evaluation protocol",
        figure_type=FigureType.RICH_SVG,
        output_dir=str(figures / "diagrams"),
        code=svg,
        metadata={
            **spec,
            "semantic_key": "evaluation_design",
            "managed_by": "merak",
            "paper_selected": True,
            "manuscript_eligible": True,
            "skill_invocation_verified": True,
            "skill_invocation_verified_by": "deterministic-runtime-figure-builder",
            "generator_skill": "deterministic-figure-template",
            "element_mappings": mappings,
        },
        artifact_name="evaluation_design",
    )

    assert result.success, result.error
    manifest = json.loads(
        (figures / "FIGURE_MANIFEST.json").read_text(encoding="utf-8")
    )
    entry = next(item for item in manifest["figures"] if item["id"] == "evaluation_design")
    assert entry["paper_ready"] is True
    assert entry["metadata"]["generator"] == "deterministic-runtime-rich-svg"
    assert entry["metadata"]["model_authored"] is False


def test_figure_producer_contract_splits_mixed_repair(tmp_path: Path) -> None:
    figures = tmp_path / "figures"
    figures.mkdir()
    figures.joinpath("FIGURE_SPECS.json").write_text(
        '{"schema":4,"publication_label_schema":1,"figures":['
        '{"id":"method_architecture","producer_kind":"model"},'
        '{"id":"evaluation_design","producer_kind":"deterministic"}]}'
    )
    producers, issues = figure_producers(
        tmp_path, ["method_architecture", "evaluation_design"],
    )
    assert issues == []
    assert producers == {
        "evaluation_design": "deterministic", "method_architecture": "model",
    }


def test_model_write_cannot_edit_deterministic_source(tmp_path: Path) -> None:
    figures = tmp_path / "figures"
    source = figures / "diagrams/evaluation_design.svg"
    source.parent.mkdir(parents=True)
    source.write_text("<svg/>")
    figures.joinpath("FIGURE_MANIFEST.json").write_text(
        '{"schema":1,"figures":[{"id":"evaluation_design",'
        '"source_path":"figures/diagrams/evaluation_design.svg",'
        '"metadata":{"producer_kind":"deterministic"}}]}'
    )
    assert "deterministic producer" in artifact_write_error(tmp_path, source)


def test_deterministic_source_is_protected_before_first_render(tmp_path: Path) -> None:
    figures = tmp_path / "figures"
    figures.mkdir()
    figures.joinpath("FIGURE_SPECS.json").write_text(
        '{"schema":4,"publication_label_schema":1,"figures":['
        '{"id":"evaluation_design","producer_kind":"deterministic"}]}'
    )
    target = figures / "diagrams/evaluation_design.svg"
    assert "deterministic producer" in artifact_write_error(tmp_path, target)


def test_failed_candidate_transaction_restores_canonical_files(tmp_path: Path) -> None:
    output_dir = tmp_path / "figures/diagrams"
    output_dir.mkdir(parents=True)
    source = output_dir / "method_architecture.svg"
    source.write_text("accepted")
    transaction = FigureFileTransaction(tmp_path, output_dir, "method_architecture")
    source.write_text("invalid candidate")
    source.with_suffix(".png").write_bytes(b"candidate")
    transaction.rollback()
    assert source.read_text() == "accepted"
    assert not source.with_suffix(".png").exists()


@pytest.mark.asyncio
async def test_engine_rejects_unreviewed_candidate_and_restores_canonical_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    ideas, figures = tmp_path / "ideas", tmp_path / "figures"
    ideas.mkdir()
    figures.mkdir()
    ideas.joinpath("SELECTED_IDEA.json").write_text(
        '{"schema":1,"status":"accepted","title":"Typed figure",'
        '"claims":[{"id":"C1","statement":"A claim"}],'
        '"mechanisms":[{"id":"M1","name":"Mechanism concept",'
        '"description":"A mechanism","required":true}],'
        '"falsification_conditions":["No effect"]}'
    )
    labels = [{
        "schema": 1, "id": "method.mechanism", "kind": "concept",
        "display_text": "Mechanism concept",
    }]
    spec = {
        "id": "typed_candidate", "scientific_role": "evaluation_design",
        "claim_ids": ["C1"], "publication_labels": labels,
        "producer_kind": "model", "recommended_backend": "rich_svg",
    }
    figures.joinpath("FIGURE_SPECS.json").write_text(
        json.dumps({
            "schema": 4, "publication_label_schema": 1, "figures": [spec],
        })
    )
    metadata = {
        **spec, "semantic_key": "typed_candidate", "managed_by": "merak",
        "paper_selected": True, "manuscript_eligible": True,
        "evidence_status": "planned_design",
    }

    async def write_candidate(
        code: str, output_dir: str, artifact_stem: str, metadata: dict,
    ) -> FigureResult:
        source = Path(output_dir) / f"{artifact_stem}.svg"
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text(code, encoding="utf-8")
        return FigureResult(
            True, FigureType.RICH_SVG, output_path=str(source),
            source_path=str(source), metadata=metadata,
        )

    monkeypatch.setattr(figure_engine, "_generate_rich_svg", write_candidate)
    source = figures / "diagrams" / "typed_candidate.svg"
    source.parent.mkdir(parents=True)
    source.write_text('<svg viewBox="0 0 800 400"><text>Accepted prior source</text></svg>', encoding="utf-8")
    accepted = source.read_bytes()
    unreviewed = await figure_engine.generate(
        "Typed method figure", FigureType.RICH_SVG, str(figures / "diagrams"),
        code='<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 400"><text>Mechanism concept</text></svg>',
        metadata=metadata, artifact_name="typed_candidate",
    )
    assert unreviewed.success is False
    assert "native-image figure review is missing" in str(unreviewed.error)
    assert source.read_bytes() == accepted
    assert not (tmp_path / ".merak/transactions").exists()


@pytest.mark.parametrize(
    ("changed", "classification"),
    [(True, "ineffective_content_change"), (False, "no_artifact_change")],
)
def test_no_progress_classifies_content_change_separately(
    changed: bool, classification: str,
) -> None:
    result = revision_stall_classification(
        target_changed=changed, resolved=[], new=[],
    )
    assert result == classification
    summary, issue = revision_stall_message(result, 2)
    if changed:
        assert "Artifacts changed" in summary
        assert "overwrote" in issue
    else:
        assert "fingerprints remained unchanged" in summary


@pytest.mark.asyncio
async def test_mixed_repair_routes_only_deterministic_asset_to_runtime(
    tmp_path: Path,
) -> None:
    figures = tmp_path / "figures"
    figures.mkdir()
    figures.joinpath("FIGURE_SPECS.json").write_text(
        '{"schema":4,"publication_label_schema":1,"figures":['
        '{"id":"method_architecture","producer_kind":"model"},'
        '{"id":"evaluation_design","producer_kind":"deterministic"}]}'
    )

    class Host:
        def __init__(self) -> None:
            self.rebuilt = set()
            self.events = []

        async def _ensure_figure_artifacts(self, _run, _result, _direction, *, target_asset_ids):
            self.rebuilt = set(target_asset_ids)

        async def _emit(self, _run, event, payload):
            self.events.append((event, payload))

    host = Host()
    model, deterministic = await rebuild_deterministic_assets(
        host, WorkflowRun(project_path=str(tmp_path)), "figure", "study", 2,
        ["method_architecture", "evaluation_design"],
    )
    assert model == ["method_architecture"]
    assert deterministic == {"evaluation_design"}
    assert host.rebuilt == {"evaluation_design"}


def test_decision_brief_reports_changed_but_unresolved_artifacts() -> None:
    diagnostics = {
        "reason": "targeted revision produced no semantic progress",
        "issues": ["same structured finding"],
        "stall_classification": "ineffective_content_change",
    }
    node = type("Node", (), {"id": "figure", "name": "画图"})()
    brief = WorkflowEngine._build_revision_decision_brief(node, diagnostics, 2, 6)
    assert "产物内容已经变化" in brief["what_happened"]
    assert "修改被其他生产者覆盖" in brief["what_happened"]


@pytest.mark.asyncio
async def test_runtime_generates_data_bound_deterministic_plot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    figures = tmp_path / "figures"
    figures.mkdir()
    data = tmp_path / "experiments/results/aggregates/main.csv"
    data.parent.mkdir(parents=True)
    data.write_text("method,mean,ci95_low,ci95_high\nA,0.7,0.6,0.8\nB,0.5,0.4,0.6\n")
    spec = {
        "id": "main_comparison", "kind": "figure",
        "producer_kind": "deterministic",
        "production_strategy": "deterministic_plot",
        "recommended_backend": "matplotlib",
        "recommended_skill": "paper-figure",
        "generation_policy": "generate",
        "data_path": "experiments/results/aggregates/main.csv",
        "scientific_question": "Which method performs better?",
        "metric": "Accuracy",
        "publication_labels": [{"schema": 1, "id": "metric.accuracy", "kind": "metric", "display_text": "Accuracy"}],
    }
    captured = {}

    async def generate(description, figure_type, output_dir, **kwargs):
        del description
        captured.update({
            "figure_type": figure_type, "output_dir": output_dir,
            "metadata": kwargs["metadata"], "code": kwargs["code"],
        })
        return FigureResult(True, figure_type, output_path="main.pdf")

    monkeypatch.setattr(figure_engine, "generate", generate)

    class Registry:
        @staticmethod
        def load(_root):
            return {"figures": []}

    class Host:
        events = []

        async def _emit(self, _run, event, payload):
            self.events.append((event, payload))

    await ensure_evaluation_design(
        Host(), WorkflowRun(project_path=str(tmp_path)), figures, [spec],
        {
            "selected_idea": "Bound comparison",
            "publication_style_contract": {"family": "machine_learning"},
        },
        set(), Registry(),
    )

    assert captured["figure_type"] == FigureType.MATPLOTLIB
    assert captured["metadata"]["producer_kind"] == "deterministic"
    assert captured["metadata"]["generator_skill"] == "paper-figure"
    assert captured["metadata"]["producer_input_sha256"]
    assert "experiments/results/aggregates/main.csv" in captured["code"]
