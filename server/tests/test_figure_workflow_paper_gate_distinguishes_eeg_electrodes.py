from __future__ import annotations

from server.tests._figure_workflow_support import (
    Path as Path,
    _build_figures as _build_figures,
    _disable_live_electron_renderer_discovery as _disable_live_electron_renderer_discovery,
    _seed_project as _seed_project,
    asyncio as asyncio,
    bind_table_manifest_hashes as bind_table_manifest_hashes,
    figure_artifact_registry as figure_artifact_registry,
    hashlib as hashlib,
    json as json,
    paper_artifact_builder as paper_artifact_builder,
    paper_budget_service as paper_budget_service,
    paper_compiler as paper_compiler,
    pytest as pytest,
    re as re,
    scientific_architecture_compiler as scientific_architecture_compiler,
    scientific_asset_service as scientific_asset_service,
)
from server.services.paper_pdf_quality import inspect_compiled_paper


def test_paper_gate_distinguishes_eeg_electrodes_from_contract_ids(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.delenv("MERAK_ENABLE_EXTERNAL_FIGURE_RENDERERS", raising=False)
    _seed_project(tmp_path)
    engine = _build_figures(tmp_path)
    evidence = paper_artifact_builder.prepare(
        tmp_path,
        "Artifact-grounded research agent",
    )
    main_path = paper_artifact_builder.write_fallback(evidence)
    plan_path = tmp_path / "figures" / "SCIENTIFIC_ASSET_PLAN.json"
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    plan.setdefault("claims", []).extend([
        {"id": "C3", "statement": "Calibration remains stable."},
        {"id": "C4", "statement": "Selective risk remains observable."},
    ])
    plan_path.write_text(json.dumps(plan), encoding="utf-8")

    manuscript = main_path.read_text(encoding="utf-8").replace(
        "\\end{document}",
        "Signals from the C3 and C4 electrodes enter the encoder.\n\\end{document}",
    )
    main_path.write_text(manuscript, encoding="utf-8")
    accepted = engine._paper_acceptance_gate(str(tmp_path))

    assert accepted["accepted"] is True, accepted

    main_path.write_text(
        manuscript.replace(
            "\\end{document}",
            "Internal claim C3 remains pending.\n\\end{document}",
        ),
        encoding="utf-8",
    )
    rejected = engine._paper_acceptance_gate(str(tmp_path))

    assert rejected["accepted"] is False
    assert any(
        "manuscript exposes internal contract IDs: C3" in problem
        for problem in rejected["details"]["issues"]
    )


def test_paper_gate_expands_input_abstract_and_table_interpretation(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.delenv("MERAK_ENABLE_EXTERNAL_FIGURE_RENDERERS", raising=False)
    _seed_project(tmp_path)
    engine = _build_figures(tmp_path)
    evidence = paper_artifact_builder.prepare(
        tmp_path,
        "Artifact-grounded research agent",
    )
    main_path = paper_artifact_builder.write_fallback(evidence)
    paper_dir = tmp_path / "paper"
    abstract = paper_dir / "sections" / "00_abstract.tex"
    abstract.parent.mkdir(parents=True, exist_ok=True)
    abstract.write_text(
        "This study defines a concrete scientific mechanism, a matched "
        "comparison, a falsification rule, and a reproducible evaluation "
        "protocol. The analysis separates measured evidence from planned "
        "tests and reports uncertainty at the independent analysis unit. " * 2,
        encoding="utf-8",
    )
    main = main_path.read_text(encoding="utf-8")
    main = re.sub(
        r"(\\begin\{abstract\}).*?(\\end\{abstract\})",
        r"\1\\input{sections/00_abstract}\2",
        main,
        flags=re.DOTALL,
    )
    main_path.write_text(main, encoding="utf-8")

    gate = engine._paper_acceptance_gate(str(tmp_path))
    problems = list(gate.get("details", {}).get("issues") or [])

    assert "abstract is missing or too short (minimum 220 characters)" not in problems
    assert not any(
        "scientific asset is referenced but not interpreted in prose: tab:method-components"
        in problem
        for problem in problems
    )


def test_paper_gate_reads_canonical_method_artifact_with_system_design_heading(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.delenv("MERAK_ENABLE_EXTERNAL_FIGURE_RENDERERS", raising=False)
    _seed_project(tmp_path)
    selected_path = tmp_path / "ideas" / "SELECTED_IDEA.json"
    selected = json.loads(selected_path.read_text(encoding="utf-8"))
    selected["mechanisms"][0].update({
        "name": "协议替代解释消融",
        "description": "Test the declared protocol alternative explanation.",
        "publication_name": "Protocol alternative explanation ablation",
        "publication_description": "Tests the declared protocol alternative explanation.",
        "publication_evaluation": "Matched protocol ablation on the primary endpoint.",
        "required": True,
    })
    selected_path.write_text(json.dumps(selected), encoding="utf-8")
    method_contract_path = tmp_path / "experiments" / "METHOD_CONTRACT.json"
    method_contract = json.loads(method_contract_path.read_text(encoding="utf-8"))
    method_contract["mechanism_coverage"] = [{
        "idea_mechanism_id": "M1",
        "required_observation": "protocol alternative explanation ablation",
    }]
    method_contract_path.write_text(
        json.dumps(method_contract),
        encoding="utf-8",
    )
    engine = _build_figures(tmp_path)
    evidence = paper_artifact_builder.prepare(
        tmp_path,
        "Artifact-grounded research agent",
    )
    main_path = paper_artifact_builder.write_fallback(evidence)
    method_path = tmp_path / "paper" / "sections" / "03_method.tex"
    method_path.parent.mkdir(parents=True, exist_ok=True)
    method_path.write_text(
        "\\section{System Design}\n"
        "We perform a protocol alternative explanation ablation under matched controls.\n",
        encoding="utf-8",
    )
    main_path.write_text(
        main_path.read_text(encoding="utf-8").replace(
            "\\end{document}",
            "\\input{sections/03_method}\n\\end{document}",
        ),
        encoding="utf-8",
    )

    gate = engine._paper_acceptance_gate(str(tmp_path))

    assert not any(
        "method section does not name required accepted mechanism" in problem
        for problem in gate.get("details", {}).get("issues", [])
    )


def test_paper_gate_allows_scientific_not_evidence_sentence(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.delenv("MERAK_ENABLE_EXTERNAL_FIGURE_RENDERERS", raising=False)
    _seed_project(tmp_path)
    engine = _build_figures(tmp_path)
    evidence = paper_artifact_builder.prepare(
        tmp_path,
        "Artifact-grounded research agent",
    )
    main_path = paper_artifact_builder.write_fallback(evidence)
    main_path.write_text(
        main_path.read_text(encoding="utf-8").replace(
            "\\end{document}",
            "Average within-dataset accuracy alone is not evidence for "
            "cross-site robustness.\n\\end{document}",
        ),
        encoding="utf-8",
    )

    accepted = engine._paper_acceptance_gate(str(tmp_path))

    assert accepted["accepted"] is True, accepted

    main_path.write_text(
        main_path.read_text(encoding="utf-8").replace(
            "\\end{document}",
            "Internal preview marker: NOT EVIDENCE.\n\\end{document}",
        ),
        encoding="utf-8",
    )
    rejected = engine._paper_acceptance_gate(str(tmp_path))

    assert rejected["accepted"] is False
    assert any(
        "evidence-administration prose at paper" in problem
        and "NOT EVIDENCE" in problem
        for problem in rejected["details"]["issues"]
    )


def test_paper_gate_uses_full_reference_paragraph_for_asset_interpretation(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.delenv("MERAK_ENABLE_EXTERNAL_FIGURE_RENDERERS", raising=False)
    _seed_project(tmp_path)
    engine = _build_figures(tmp_path)
    evidence = paper_artifact_builder.prepare(
        tmp_path,
        "Artifact-grounded research agent",
    )
    main_path = paper_artifact_builder.write_fallback(evidence)
    manuscript = main_path.read_text(encoding="utf-8")
    old_sentence = (
        "Figure~\\ref{fig:method-architecture} summarizes the scientific "
        "pipeline from study inputs through the proposed mechanisms to the "
        "reported endpoints."
    )
    long_neutral_context = " ".join(["Context"] * 75)
    new_sentence = (
        "Figure~\\ref{fig:method-architecture} accompanies this section. "
        + long_neutral_context
        + " The asset should be interpreted as a map of the controlled "
        "comparison."
    )
    assert old_sentence in manuscript
    main_path.write_text(
        manuscript.replace(old_sentence, new_sentence),
        encoding="utf-8",
    )

    gate = engine._paper_acceptance_gate(str(tmp_path))

    assert not any(
        "scientific asset is referenced but not interpreted in prose: "
        "fig:method-architecture" in problem
        for problem in gate.get("details", {}).get("issues", [])
    )


def test_paper_gate_accepts_comparison_noun_as_asset_interpretation(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.delenv("MERAK_ENABLE_EXTERNAL_FIGURE_RENDERERS", raising=False)
    _seed_project(tmp_path)
    engine = _build_figures(tmp_path)
    evidence = paper_artifact_builder.prepare(
        tmp_path,
        "Artifact-grounded research agent",
    )
    main_path = paper_artifact_builder.write_fallback(evidence)
    manuscript = main_path.read_text(encoding="utf-8")
    old_sentence = (
        "Figure~\\ref{fig:method-architecture} summarizes the scientific "
        "pipeline from study inputs through the proposed mechanisms to the "
        "reported endpoints."
    )
    new_sentence = (
        "Figure~\\ref{fig:method-architecture} gives the controlled comparison "
        "between study inputs, mechanisms, and reported endpoints."
    )
    assert old_sentence in manuscript
    main_path.write_text(
        manuscript.replace(old_sentence, new_sentence),
        encoding="utf-8",
    )

    gate = engine._paper_acceptance_gate(str(tmp_path))

    assert not any(
        "scientific asset is referenced but not interpreted in prose: "
        "fig:method-architecture" in problem
        for problem in gate.get("details", {}).get("issues", [])
    )


def test_paper_gate_allows_continuation_table_to_share_parent_reference(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.delenv("MERAK_ENABLE_EXTERNAL_FIGURE_RENDERERS", raising=False)
    _seed_project(tmp_path)
    engine = _build_figures(tmp_path)
    evidence = paper_artifact_builder.prepare(
        tmp_path,
        "Artifact-grounded research agent",
    )
    paper_artifact_builder.write_fallback(evidence)
    table_path = tmp_path / "paper" / "tables" / "study_design.tex"
    table_path.write_text(
        table_path.read_text(encoding="utf-8")
        + "\n"
        + "\\begin{table}[t]\n"
        + "\\caption{Study dimensions (continued).}\n"
        + "\\label{tab:study-design-continued}\n"
        + "\\begin{tabular}{ll}Setting & Purpose \\\\\\\\\n"
        + "Seed & Uncertainty \\\\\\\\\n"
        + "\\end{tabular}\n"
        + "\\end{table}\n",
        encoding="utf-8",
    )
    manifest_path = tmp_path / "paper" / "tables" / "TABLE_MANIFEST.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for table in manifest.get("tables", []):
        if table.get("id") == "study_design":
            table["latex_sha256"] = hashlib.sha256(table_path.read_bytes()).hexdigest()
    manifest, issues, _ = bind_table_manifest_hashes(tmp_path, manifest)
    assert not issues
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    gate = engine._paper_acceptance_gate(str(tmp_path))

    assert gate["accepted"] is True, gate


def test_evidence_grounded_paper_compiles_with_figures_and_tables(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.delenv("MERAK_ENABLE_EXTERNAL_FIGURE_RENDERERS", raising=False)
    _seed_project(tmp_path)
    engine = _build_figures(tmp_path)
    evidence = paper_artifact_builder.prepare(
        tmp_path,
        "Artifact-grounded research agent",
    )
    paper_artifact_builder.write_fallback(evidence)

    gate = engine._paper_acceptance_gate(str(tmp_path))
    assert gate["accepted"] is True, gate

    compiled = asyncio.run(
        paper_compiler.compile(str(tmp_path / "paper"), "main.tex")
    )
    assert compiled.success is True, compiled.log_output
    assert compiled.pdf_path
    assert Path(compiled.pdf_path).is_file()
    assert Path(compiled.pdf_path).stat().st_size > 0
    assert compiled.pages > 0
    _, layout_issues = inspect_compiled_paper(
        paper_compiler, tmp_path, compiled.pdf_path,
    )
    assert not layout_issues

    target_pages = max(4, compiled.pages)
    tolerance = min(5, abs(target_pages - compiled.pages))
    budget = paper_budget_service.prepare(tmp_path, target_pages, tolerance, "ICLR")
    assert budget is not None
    build_path = tmp_path / "paper" / "PAPER_BUILD.json"
    build_path.write_text(
        json.dumps({"compile": {"pages": compiled.pages}}),
        encoding="utf-8",
    )
    page_gate = engine._paper_acceptance_gate(str(tmp_path), require_page_budget=True)
    assert page_gate["accepted"] is True, page_gate

    build_path.write_text(
        json.dumps({"compile": {"pages": budget.maximum_pages + 1}}),
        encoding="utf-8",
    )
    soft_page_gate = engine._paper_acceptance_gate(str(tmp_path), require_page_budget=True)
    assert soft_page_gate["accepted"] is True
    assert any(
        "outside the preferred range" in warning
        for warning in soft_page_gate["details"]["warnings"]
    )


def test_synthetic_mode_builds_complete_scientific_asset_generation(
    tmp_path: Path,
) -> None:
    _seed_project(tmp_path)

    plan = scientific_asset_service.build_plan(
        tmp_path,
        experiment_requested=False,
        requested_evidence_mode="synthetic_preview",
    )

    assert plan["evidence_mode"] == "synthetic_preview"
    assert plan["requested_evidence_mode"] == "synthetic_preview"
    assert plan["quantitative_figure_policy"] == "complete_benchmark"
    assert plan["submission_eligible"] is True
    figures = [item for item in plan["assets"] if item.get("kind") == "figure"]
    assert {item["id"] for item in figures} == {
        "method_architecture", "evaluation_design",
    }
    assert all(item["generation_phase"] == "phase_2b" for item in figures)


def test_scientific_asset_plan_defaults_to_auto_and_rejects_disabled_mode(
    tmp_path: Path,
) -> None:
    _seed_project(tmp_path)

    auto_plan = scientific_asset_service.build_plan(
        tmp_path,
        experiment_requested=False,
        illustration_mode="auto",
    )
    auto_figures = {
        item["id"]: item
        for item in auto_plan["assets"]
        if item.get("kind") == "figure"
    }
    assert auto_figures["method_architecture"]["production_strategy"] == "deterministic_architecture"
    assert auto_figures["method_architecture"]["recommended_backend"] == "figurespec"
    assert auto_figures["evaluation_design"]["recommended_backend"] == "rich_svg"

    assert auto_plan["illustration_mode"] == "auto"
    assert all(item["required"] is True for item in auto_figures.values())
    assert all(item["manuscript_eligible"] is True for item in auto_figures.values())
    assert all(item["generation_policy"] == "generate" for item in auto_figures.values())
    with pytest.raises(ValueError, match="unsupported illustration mode: false"):
        scientific_asset_service.build_plan(
            tmp_path,
            experiment_requested=False,
            illustration_mode="false",
        )


def test_method_architecture_is_extracted_from_implementation_symbols(
    tmp_path: Path,
) -> None:
    _seed_project(tmp_path)
    models_path = tmp_path / "experiments" / "src" / "models.py"
    models_path.write_text(
        "from torch import nn\n\n"
        "class MaskedEEGEncoder(nn.Module):\n"
        "    def __init__(self, channels, hidden, depth):\n"
        "        super().__init__()\n"
        "        self.patch = nn.Conv1d(channels, hidden, 16, 16)\n"
        "        self.encoder = nn.TransformerEncoder(nn.Identity(), depth)\n"
        "        self.decoder = nn.Linear(hidden, channels * 16)\n"
        "    def forward(self, signal):\n"
        "        tokens = self.patch(signal)\n"
        "        encoded = self.encoder(tokens)\n"
        "        reconstruction = self.decoder(encoded)\n"
        "        return encoded, reconstruction\n",
        encoding="utf-8",
    )
    method_contract_path = tmp_path / "experiments" / "METHOD_CONTRACT.json"
    method_contract = json.loads(method_contract_path.read_text(encoding="utf-8"))
    method_contract["implementation_checks"] = [{
        "id": "I1",
        "description": "Masked EEG representation and reconstruction objective",
        "evidence": [{
            "path": "experiments/src/models.py",
            "symbols": ["MaskedEEGEncoder"],
        }],
    }]
    method_contract_path.write_text(json.dumps(method_contract), encoding="utf-8")

    plan = scientific_asset_service.build_plan(
        tmp_path,
        experiment_requested=False,
        illustration_mode="auto",
    )
    method = next(
        item for item in plan["assets"]
        if item.get("id") == "method_architecture"
    )
    blueprint = method["architecture_blueprint"]
    labels = {item["label"] for item in blueprint["components"]}

    assert {"MaskedEEGEncoder", "Patch", "Encoder", "Decoder"} <= labels
    assert blueprint["tensor_flow"]
    assert "experiments/src/models.py" in blueprint["source_paths"]
    assert method["production_strategy"] == "deterministic_architecture"
    assert method["recommended_backend"] == "figurespec"


def test_architecture_blueprint_deduplicates_repeated_symbols_and_flows(
    tmp_path: Path,
) -> None:
    _seed_project(tmp_path)
    models_path = tmp_path / "experiments" / "src" / "models.py"
    models_path.write_text(
        "from torch import nn\n\n"
        "class SharedEncoder(nn.Module):\n"
        "    def __init__(self):\n"
        "        super().__init__()\n"
        "        self.stem = nn.Linear(4, 8)\n"
        "    def forward(self, x):\n"
        "        z = self.stem(x)\n"
        "        return z\n",
        encoding="utf-8",
    )
    method_contract_path = tmp_path / "experiments" / "METHOD_CONTRACT.json"
    method_contract = json.loads(method_contract_path.read_text(encoding="utf-8"))
    method_contract["implementation_checks"] = [
        {
            "id": "I1",
            "description": "Shared representation encoder",
            "evidence": [{
                "path": "experiments/src/models.py",
                "symbols": ["SharedEncoder"],
            }],
        },
        {
            "id": "I2",
            "description": "The same encoder is used by another objective",
            "evidence": [{
                "path": "experiments/src/models.py",
                "symbols": ["SharedEncoder"],
            }],
        },
    ]
    method_contract_path.write_text(json.dumps(method_contract), encoding="utf-8")

    plan = scientific_asset_service.build_plan(
        tmp_path,
        experiment_requested=False,
    )
    method = next(item for item in plan["assets"] if item["id"] == "method_architecture")
    blueprint = method["architecture_blueprint"]
    component_keys = [
        (item["source_path"], item["source_symbol"])
        for item in blueprint["components"]
    ]
    flow_keys = [
        (
            item["from"], item["to"], item["operation"],
            item["source_path"], item["source_symbol"],
        )
        for item in blueprint["tensor_flow"]
    ]

    assert len(component_keys) == len(set(component_keys))
    assert len(flow_keys) == len(set(flow_keys))
    assert not any("_2" in item["from"] or "_2" in item["to"] for item in blueprint["tensor_flow"])


def test_architecture_blueprint_resolves_nested_calls_and_shared_module_aliases(
    tmp_path: Path,
) -> None:
    _seed_project(tmp_path)
    models_path = tmp_path / "experiments" / "src" / "models.py"
    models_path.write_text(
        "from torch import nn\n\n"
        "class Encoder(nn.Module):\n"
        "    def __init__(self):\n"
        "        super().__init__()\n"
        "        self.stem = nn.Linear(4, 8)\n"
        "        self.pool = nn.Identity()\n"
        "        self.projection = nn.Linear(8, 8)\n"
        "    def forward(self, x):\n"
        "        h = self.stem(x)\n"
        "        return self.projection(self.pool(h))\n\n"
        "class Decoder(nn.Module):\n"
        "    def __init__(self):\n"
        "        super().__init__()\n"
        "        self.layer = nn.Linear(8, 4)\n"
        "    def forward(self, z):\n"
        "        return self.layer(z).view(-1, 4)\n\n"
        "class ObjectiveModel(nn.Module):\n"
        "    def __init__(self):\n"
        "        super().__init__()\n"
        "        self.encoder = Encoder()\n"
        "        self.decoder = Decoder()\n"
        "    def forward(self, x):\n"
        "        z = self.encoder(x)\n"
        "        return z, self.decoder(z)\n",
        encoding="utf-8",
    )
    method_contract_path = tmp_path / "experiments" / "METHOD_CONTRACT.json"
    method_contract = json.loads(method_contract_path.read_text(encoding="utf-8"))
    method_contract["implementation_checks"] = [{
        "id": "I1",
        "description": "Shared representation with a reconstruction objective",
        "evidence": [{
            "path": "experiments/src/models.py",
            "symbols": ["Encoder", "Decoder", "ObjectiveModel"],
        }],
    }]
    method_contract["evaluation_contract"]["primary_outcomes"] = [
        "classification accuracy",
    ]
    method_contract_path.write_text(json.dumps(method_contract), encoding="utf-8")

    plan = scientific_asset_service.build_plan(
        tmp_path,
        experiment_requested=False,
    )
    method = next(item for item in plan["assets"] if item["id"] == "method_architecture")
    blueprint = method["architecture_blueprint"]
    component_ids = {item["id"] for item in blueprint["components"]}
    symbols = {item["source_symbol"] for item in blueprint["components"]}
    labels_by_id = {
        item["id"]: item["label"] for item in blueprint["components"]
    }
    data_edges = [
        (labels_by_id[item["from"]], labels_by_id[item["to"]])
        for item in blueprint["tensor_flow"]
        if item.get("flow_kind") == "data"
    ]

    assert "ObjectiveModel.encoder" not in symbols
    assert "ObjectiveModel.decoder" not in symbols
    assert ("Stem", "Pool") in data_edges
    assert ("Pool", "Projection") in data_edges
    assert ("Projection", "Layer") in data_edges
    assert any(
        item.get("evidence_status") == "contract_inferred"
        and item["label"] == "Downstream Task Head"
        for item in blueprint["components"]
    )
    assert blueprint["inference_paths"]
    assert not any(
        item["from"] not in component_ids or item["to"] not in component_ids
        for item in blueprint["tensor_flow"]
    )


def test_architecture_blueprint_expands_forward_only_evidence_and_hides_plumbing(
    tmp_path: Path,
) -> None:
    _seed_project(tmp_path)
    models_path = tmp_path / "experiments" / "src" / "models.py"
    models_path.write_text(
        "from torch import nn\n\n"
        "class ObjectiveModel(nn.Module):\n"
        "    def __init__(self):\n"
        "        super().__init__()\n"
        "        self.tokenizer = nn.Conv1d(8, 64, 8, 8)\n"
        "        self.encoder = nn.TransformerEncoder(nn.Identity(), 4)\n"
        "        self.decoder = nn.Linear(64, 8)\n"
        "        self.task_head = nn.Linear(64, 3)\n"
        "    def forward(self, x):\n"
        "        tokens = self.tokenizer(x)\n"
        "        encoded = self.encoder(tokens)\n"
        "        return self.decoder(encoded), self.task_head(encoded)\n",
        encoding="utf-8",
    )
    method_contract_path = tmp_path / "experiments" / "METHOD_CONTRACT.json"
    method_contract = json.loads(method_contract_path.read_text(encoding="utf-8"))
    method_contract["implementation_checks"] = [{
        "id": "I1",
        "description": "Tokenization, shared encoding, reconstruction, and prediction",
        "evidence": [{
            "path": "experiments/src/models.py",
            "symbols": ["ObjectiveModel.forward"],
        }],
    }]
    method_contract_path.write_text(json.dumps(method_contract), encoding="utf-8")

    plan = scientific_asset_service.build_plan(tmp_path, experiment_requested=False)
    method = next(item for item in plan["assets"] if item["id"] == "method_architecture")
    blueprint = method["architecture_blueprint"]
    by_symbol = {
        item["source_symbol"]: item for item in blueprint["components"]
    }

    assert {
        "ObjectiveModel.tokenizer",
        "ObjectiveModel.encoder",
        "ObjectiveModel.decoder",
        "ObjectiveModel.task_head",
    } <= set(by_symbol)
    assert by_symbol["ObjectiveModel.forward"]["required_visual"] is False
    assert by_symbol["ObjectiveModel.forward"]["publication_visible"] is False
    assert blueprint["inference_paths"]


def test_architecture_blueprint_discovers_predictive_head_in_admitted_module(
    tmp_path: Path,
) -> None:
    _seed_project(tmp_path)
    models_path = tmp_path / "experiments" / "src" / "models.py"
    models_path.write_text(
        "from torch import nn\n\n"
        "class AblationSwitches:\n"
        "    pass\n\n"
        "class BenchmarkClassifier(nn.Module):\n"
        "    def __init__(self):\n"
        "        super().__init__()\n"
        "        self.encoder = nn.Linear(4, 8)\n"
        "        self.task_head = nn.Linear(8, 2)\n"
        "    def forward(self, x):\n"
        "        representation = self.encoder(x)\n"
        "        return {'logits': self.task_head(representation)}\n",
        encoding="utf-8",
    )
    method_contract_path = tmp_path / "experiments" / "METHOD_CONTRACT.json"
    method_contract = json.loads(method_contract_path.read_text(encoding="utf-8"))
    method_contract["implementation_checks"] = [{
        "id": "I1",
        "description": "Single-factor ablation control",
        "evidence": [{
            "path": "experiments/src/models.py",
            "symbols": ["AblationSwitches"],
        }],
    }]
    method_contract["evaluation_contract"]["primary_outcomes"] = [
        "classification accuracy",
    ]
    method_contract_path.write_text(json.dumps(method_contract), encoding="utf-8")

    plan = scientific_asset_service.build_plan(tmp_path, experiment_requested=False)
    method = next(item for item in plan["assets"] if item["id"] == "method_architecture")
    blueprint = method["architecture_blueprint"]
    symbols = {
        item["source_symbol"]: item for item in blueprint["components"]
    }

    assert "BenchmarkClassifier.task_head" in symbols
    assert symbols["BenchmarkClassifier.task_head"].get("evidence_status") != "contract_inferred"
    assert not any(
        "no classifier/task head" in issue
        for issue in blueprint["completeness_issues"]
    )


def test_method_brief_reads_model_task_dataset_and_conditions_from_config(
    tmp_path: Path,
) -> None:
    _seed_project(tmp_path)
    (tmp_path / "experiments" / "configs" / "main.yaml").write_text(
        "model:\n"
        "  architecture: CrossDomainTransformer\n"
        "data:\n"
        "  dataset_id: HeldOutAtlas\n"
        "evaluation:\n"
        "  task_type: multiclass_classification_pending_data_compatibility\n"
        "experiment:\n"
        "  objective_conditions:\n"
        "    - contrastive_only\n"
        "    - masked_only\n"
        "    - joint_objective\n",
        encoding="utf-8",
    )

    plan = scientific_asset_service.build_plan(tmp_path, experiment_requested=False)
    method = next(item for item in plan["assets"] if item["id"] == "method_architecture")
    brief = method["method_brief"]

    assert "CrossDomainTransformer" in brief["models"]
    assert "HeldOutAtlas" in brief["datasets"]
    assert "multiclass classification" in brief["tasks"]
    assert not any("pending" in item.casefold() for item in brief["tasks"])
    assert {
        "contrastive only", "masked only", "joint objective",
    } <= set(brief["study_conditions"])


def test_scientific_architecture_compiler_uses_diverse_domain_primitives() -> None:
    components = [
        {"id": "manifest", "label": "Signal manifest", "lane": "data_and_sampling", "source_path": "experiments/src/data.py", "source_symbol": "load_manifest"},
        {"id": "split", "label": "Grouped split", "lane": "data_and_sampling", "source_path": "experiments/src/data.py", "source_symbol": "grouped_split"},
        {"id": "mask", "label": "Topology mask", "lane": "data_and_sampling", "source_path": "experiments/src/data.py", "source_symbol": "topology_mask"},
        {"id": "stem", "label": "Temporal stem", "lane": "representation_model", "source_path": "experiments/src/models.py", "source_symbol": "Encoder.stem", "operation": "nn.Conv1d(16, 128, 7)"},
        {"id": "blocks", "label": "Residual blocks", "lane": "representation_model", "source_path": "experiments/src/models.py", "source_symbol": "Encoder.blocks"},
        {"id": "pool", "label": "Global pool", "lane": "representation_model", "source_path": "experiments/src/models.py", "source_symbol": "Encoder.pool"},
        {"id": "projection", "label": "Projection", "lane": "representation_model", "source_path": "experiments/src/models.py", "source_symbol": "Encoder.projection"},
        {"id": "contrastive", "label": "Temporal NT-Xent", "lane": "training_objective", "source_path": "experiments/src/objectives.py", "source_symbol": "temporal_nt_xent"},
        {"id": "decoder", "label": "Reconstruction decoder", "lane": "training_objective", "source_path": "experiments/src/models.py", "source_symbol": "Decoder.layer"},
        {"id": "task", "label": "Downstream task head", "lane": "evaluation", "source_path": "experiments/METHOD_CONTRACT.json", "source_symbol": "evaluation_contract.primary_outcomes"},
        {"id": "audit", "label": "Split audit", "lane": "diagnostics_and_accounting", "source_path": "experiments/src/data.py", "source_symbol": "SplitAudit"},
    ]
    compilation = scientific_architecture_compiler.compile({
        "architecture_blueprint": {
            "components": components,
            "tensor_flow": [],
            "training_paths": [["manifest", "split", "stem", "blocks", "pool", "projection", "contrastive"]],
            "inference_paths": [["manifest", "split", "stem", "blocks", "pool", "projection", "task"]],
            "configuration_constraints": [{"source_path": "experiments/configs/main.yaml"}],
            "implementation_status": "contract_mapped",
        },
        "method_brief": {
            "title": "Matched hybrid representation study",
            "endpoints": ["balanced accuracy", "AUROC", "ECE"],
        },
    })

    visual_kinds = {
        item["visual_kind"] for item in compilation.spec["nodes"]
    }
    assert {
        "signal", "database", "matrix", "tensor_stack", "module_stack",
        "pooling", "embedding", "loss", "decoder", "head", "metric_card",
    } <= visual_kinds
    assert figure_artifact_registry.figurespec_layout_issues_payload(
        compilation.spec
    ) == []
    assert len(compilation.element_mappings) == len(compilation.spec["nodes"])


def test_scientific_architecture_compiler_never_renders_plumbing_symbols() -> None:
    compilation = scientific_architecture_compiler.compile({
        "architecture_blueprint": {
            "components": [
                {
                    "id": "main", "label": "main", "display_name": "Training entry",
                    "lane": "representation_model", "source_path": "experiments/src/train.py",
                    "source_symbol": "main", "publication_visible": False,
                },
                {
                    "id": "encoder", "label": "Encoder", "display_name": "Shared encoder",
                    "lane": "representation_model", "source_path": "experiments/src/models.py",
                    "source_symbol": "Model.encoder", "publication_visible": True,
                    "operation": "nn.TransformerEncoder(nn.Identity(), 4)",
                },
                {
                    "id": "head", "label": "Task Head", "display_name": "Prediction head",
                    "lane": "evaluation", "source_path": "experiments/src/models.py",
                    "source_symbol": "Model.task_head", "publication_visible": True,
                },
            ],
            "inference_paths": [["main", "encoder", "head"]],
        },
        "method_brief": {"title": "Project-specific predictive architecture"},
    })

    visible_text = " ".join(
        f"{node.get('label') or ''} {node.get('sublabel') or ''}"
        for node in compilation.spec["nodes"]
    ).casefold()
    assert "training entry" not in visible_text
    assert "nn." not in visible_text
    assert "transformerencoder(" not in visible_text
    assert "model.encoder" not in visible_text
    assert not any(
        mapping.get("source_symbol") == "main"
        for mapping in compilation.element_mappings
    )


def test_scientific_architecture_compiler_projects_function_lists_to_mechanism_story() -> None:
    components = [
        {"id": "rows", "label": "Rows", "lane": "data_and_sampling", "source_path": "experiments/src/data.py", "source_symbol": "EEGManifestDataset.rows"},
        {"id": "condition", "label": "GeometryCondition", "lane": "data_and_sampling", "source_path": "experiments/src/data.py", "source_symbol": "GeometryCondition"},
        {"id": "collate", "label": "collate eeg batch", "lane": "data_and_sampling", "source_path": "experiments/src/data.py", "source_symbol": "collate_eeg_batch"},
        {"id": "main", "label": "main", "lane": "representation_model", "source_path": "experiments/src/train.py", "source_symbol": "main"},
        {"id": "forward", "label": "forward", "lane": "representation_model", "source_path": "experiments/src/models.py", "source_symbol": "ConditionalMaskEEG.forward"},
        {"id": "objective", "label": "compute objectives", "lane": "training_objective", "source_path": "experiments/src/objectives.py", "source_symbol": "compute_objectives"},
        {"id": "metrics", "label": "registered metric records", "lane": "evaluation", "source_path": "experiments/src/evaluation.py", "source_symbol": "registered_metric_records"},
    ]
    compilation = scientific_architecture_compiler.compile({
        "architecture_blueprint": {
            "components": components,
            "implementation_status": "contract_mapped",
        },
        "method_brief": {
            "title": "Conditional mask geometry mechanism map",
            "problem": "EEG masked representation learning",
            "mechanism_nodes": [
                {"name": "掩码几何条件化干预", "description": "比较保留率、时间聚集度和跨通道同步性。"},
                {"name": "任务形态与域留出交互估计", "description": "比较连续状态、事件任务和留出域。"},
                {"name": "捷径与塌缩排除读出", "description": "检查塌缩、可恢复性和身份捷径。"},
            ],
            "reported_endpoints": ["held-out accuracy", "interaction"],
        },
    })

    labels = {item["label"] for item in compilation.spec["nodes"]}
    assert "Conditional Mask Geometry" in labels
    assert "Task × Domain Interaction" in labels
    assert "Shortcut & Collapse Diagnostics" in labels
    assert {"main", "Rows", "collate eeg batch"}.isdisjoint(labels)
    assert compilation.profile["semantic_aggregation"] is True
    assert set(compilation.profile["covered_component_ids"]) == {
        item["id"] for item in components
    }
    assert len(compilation.element_mappings) == len(components)
    assert figure_artifact_registry.figurespec_layout_issues_payload(
        compilation.spec
    ) == []
