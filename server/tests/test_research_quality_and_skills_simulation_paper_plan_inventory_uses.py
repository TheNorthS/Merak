from __future__ import annotations

from server.tests._research_quality_and_skills_support import (
    Path as Path,
    WorkflowEngine as WorkflowEngine,
    WorkflowNode as WorkflowNode,
    WorkflowRun as WorkflowRun,
    _write_method_contract as _write_method_contract,
    _write_selected_idea_contract as _write_selected_idea_contract,
    asyncio as asyncio,
    invoke_skill as invoke_skill,
    json as json,
    method_contract_service as method_contract_service,
    pytest as pytest,
    research_quality_service as research_quality_service,
    subprocess as subprocess,
    sys as sys,
)


def test_simulation_paper_plan_inventory_uses_results_not_empty_templates(
    tmp_path: Path,
    monkeypatch,
) -> None:
    (tmp_path / "paper").mkdir()
    (tmp_path / "NARRATIVE_REPORT.md").write_text(
        "# Narrative\nA complete deterministic benchmark narrative.",
        encoding="utf-8",
    )
    templates = tmp_path / "experiments" / "results" / "templates"
    simulated = tmp_path / "experiments" / "results" / "simulated"
    templates.mkdir(parents=True)
    simulated.mkdir(parents=True)
    (templates / "main_comparison.csv").write_text(
        "status,value\nplanned,\n", encoding="utf-8"
    )
    (simulated / "main_comparison.csv").write_text(
        "status,value\nsynthetic_preview,0.81\n", encoding="utf-8"
    )
    (simulated / "claim_evidence.csv").write_text(
        "claim_id,claim_status\nC1,supported\n", encoding="utf-8"
    )
    calls: list[str] = []

    async def fake_invoke(
        skill_name: str,
        arguments: str = "",
        project_path: str = "",
        parent_context: str = "",
        on_event=None,
    ) -> str:
        calls.append(arguments)
        body = (
            "# Paper Plan\n\n## One-sentence contribution\nA bounded result.\n\n"
            "## Claims-Evidence Matrix\nC1 is supported.\n\n"
            "## Section Plan\nIntroduction, Method, Results, Conclusion.\n\n"
            "## Figure Plan\nA main result figure.\n\n"
            + ("Grounded section detail. " * 40)
        )
        (tmp_path / "paper" / "PAPER_PLAN.md").write_text(body, encoding="utf-8")
        return "Canonical paper plan written."

    import server.agent.tools as agent_tools

    monkeypatch.setattr(agent_tools, "invoke_skill", fake_invoke)
    run = WorkflowRun(
        id="simulation-paper-plan-run",
        project_path=str(tmp_path),
        created_at=1.0,
        options={"non_experiment_evidence_mode": "synthetic_preview"},
    )
    asyncio.run(
        WorkflowEngine()._execute_stage_delegates(
            node=WorkflowNode(
                id="narrative", name="Narrative", skill="/research-refine"
            ),
            run=run,
            direction="benchmark",
            effort="balanced",
            assurance="submission",
            opts=run.options,
        )
    )

    assert len(calls) == 1
    assert "experiments/results/simulated/main_comparison.csv" in calls[0]
    assert "experiments/results/simulated/claim_evidence.csv" in calls[0]
    assert "experiments/results/templates/main_comparison.csv" not in calls[0]
    assert "use maturity `benchmark-supported`" in calls[0]


def test_exp_design_selects_ranked_top_one_instead_of_ideas_title(tmp_path: Path) -> None:
    ideas = tmp_path / "ideas"
    ideas.mkdir()
    (ideas / "ideas.md").write_text(
        """# Research Ideas for EEG Foundation Models

| Rank | Idea | Rationale |
|---|---|---|
| 1 | Montage-Stress Geometry-Aware EEG Foundation Model | strongest testable delta |
| 2 | Generic EEG Adapter | lower risk |
""",
        encoding="utf-8",
    )
    selected = WorkflowEngine()._extract_selected_idea(
        tmp_path,
        "The stream stopped before the final write.",
        "EEG foundation models",
    )
    assert selected == "Montage-Stress Geometry-Aware EEG Foundation Model"


def test_canonical_novelty_top_one_overrides_generic_model_summary(tmp_path: Path) -> None:
    ideas = tmp_path / "ideas"
    ideas.mkdir()
    (ideas / "novelty_report.md").write_text(
        "# Novelty Report\n\nRecommended Top-1: Montage-Aware Masked EEG Foundation Model\n",
        encoding="utf-8",
    )

    selected = WorkflowEngine()._extract_selected_idea(
        tmp_path,
        "Use a simple CNN because it is easy to execute.",
        "EEG foundation models",
    )

    assert selected == "Montage-Aware Masked EEG Foundation Model"


def test_exp_design_rejects_missing_selected_idea_contract(
    tmp_path: Path,
) -> None:
    ideas = tmp_path / "ideas"
    ideas.mkdir()
    (ideas / "novelty_report.md").write_text(
        "Recommended Top-1: Evidence-Grounded Adaptive Controller\n"
        "Mechanism: update the controller from measured residuals.\n"
        "Falsification: residuals do not improve under matched controls.\n",
        encoding="utf-8",
    )
    run = WorkflowRun(project_path=str(tmp_path))

    with pytest.raises(ValueError, match="repair the novelty owner"):
        WorkflowEngine()._input_exp_design("adaptive control", {}, run)
    assert not (ideas / "SELECTED_IDEA.json").exists()


def test_exp_design_gate_rejects_an_undeclared_substitute_for_the_selected_method(
    tmp_path: Path,
) -> None:
    title = "Montage-Aware Masked EEG Foundation Model"
    _write_selected_idea_contract(
        tmp_path,
        title,
        [
            {"id": "M1", "name": "Montage adaptation", "description": "Adapt observed sensor sets.", "required": True},
            {"id": "M2", "name": "Masked objective", "description": "Learn from held-out observations.", "required": True},
        ],
    )
    (tmp_path / "experiments" / "src").mkdir(parents=True)
    (tmp_path / "experiments" / "configs").mkdir()
    (tmp_path / "experiments" / "EXPERIMENT_PLAN.md").write_text(
        f"# Experiment Plan\nAuto-selected idea: {title}\n",
        encoding="utf-8",
    )
    (tmp_path / "experiments" / "configs" / "main.yaml").write_text(
        "experiment:\n  implementation_status: complete\n",
        encoding="utf-8",
    )
    (tmp_path / "experiments" / "src" / "models.py").write_text(
        """import torch
from torch import nn

class SimpleCNN(nn.Module):
    def __init__(self):
        super().__init__()
        self.net = nn.Sequential(nn.Conv1d(19, 32, 3), nn.ReLU(), nn.AdaptiveAvgPool1d(1))

    def forward(self, x):
        return self.net(x).squeeze(-1)
""",
        encoding="utf-8",
    )
    _write_method_contract(
        tmp_path,
        title,
        [
            {
                "id": "I1",
                "description": "Montage mechanism implementation",
                "evidence": [{"path": "experiments/src/models.py", "symbols": ["MontageAdapter"]}],
            },
            {
                "id": "I2",
                "description": "Masked objective implementation",
                "evidence": [{"path": "experiments/src/models.py", "symbols": ["masked_pretrain"]}],
            },
        ],
        [
            {"idea_mechanism_id": "M1", "implementation_check_ids": ["I1"]},
            {"idea_mechanism_id": "M2", "implementation_check_ids": ["I2"]},
        ],
    )

    gate = WorkflowEngine()._exp_design_method_alignment_gate(
        WorkflowRun(project_path=str(tmp_path)),
        "EEG foundation models",
    )

    assert gate["accepted"] is False
    assert any("missing declared symbol" in issue for issue in gate["details"]["issues"])
    assert all("CNN" not in issue for issue in gate["details"]["issues"])


def test_exp_design_gate_accepts_executable_selected_mechanism(tmp_path: Path) -> None:
    title = "Montage-Aware Masked EEG Foundation Model"
    _write_selected_idea_contract(
        tmp_path,
        title,
        [
            {"id": "M1", "name": "Montage adaptation", "description": "Adapt observed sensor sets.", "required": True},
            {"id": "M2", "name": "Masked objective", "description": "Learn from held-out observations.", "required": True},
        ],
    )
    (tmp_path / "experiments" / "src").mkdir(parents=True)
    (tmp_path / "experiments" / "configs").mkdir()
    (tmp_path / "experiments" / "EXPERIMENT_PLAN.md").write_text(
        """# Experiment Plan
Auto-selected idea: Montage-Aware Masked EEG Foundation Model
The montage adapter maps electrode coordinates and channel masks into latent tokens.
Masked pretraining reconstructs held-out EEG patches before downstream transfer.
""",
        encoding="utf-8",
    )
    (tmp_path / "experiments" / "configs" / "main.yaml").write_text(
        """experiment:
  selected_idea: Montage-Aware Masked EEG Foundation Model
  implementation_status: complete
training:
  objective: masked_reconstruction
""",
        encoding="utf-8",
    )
    (tmp_path / "experiments" / "src" / "models.py").write_text(
        """import torch
from torch import nn

class MontageAdapter(nn.Module):
    def __init__(self, input_dim=128, latent_dim=128):
        super().__init__()
        self.coordinate_encoder = nn.Sequential(
            nn.Linear(3, latent_dim),
            nn.GELU(),
            nn.Linear(latent_dim, latent_dim),
        )
        self.channel_adapter = nn.Linear(input_dim, latent_dim)

    def forward(self, channel_tokens, electrode_coordinates, channel_mask):
        spatial = self.coordinate_encoder(electrode_coordinates)
        adapted = self.channel_adapter(channel_tokens) + spatial
        return adapted * channel_mask.unsqueeze(-1)

class MaskedEEGFoundationEncoder(nn.Module):
    def __init__(self, input_dim=128, hidden_dim=128, heads=4):
        super().__init__()
        self.montage_adapter = MontageAdapter(input_dim, hidden_dim)
        self.mask_token = nn.Parameter(torch.zeros(1, 1, hidden_dim))
        self.attention = nn.MultiheadAttention(hidden_dim, heads, batch_first=True)
        self.encoder = nn.Sequential(
            nn.LayerNorm(hidden_dim),
            nn.Linear(hidden_dim, hidden_dim * 4),
            nn.GELU(),
            nn.Linear(hidden_dim * 4, hidden_dim),
        )
        self.reconstruction_head = nn.Linear(hidden_dim, input_dim)

    def tokenize(self, eeg_patches, electrode_coordinates, channel_mask):
        return self.montage_adapter(eeg_patches, electrode_coordinates, channel_mask)

    def masked_pretrain(self, eeg_patches, electrode_coordinates, channel_mask, patch_mask):
        tokens = self.tokenize(eeg_patches, electrode_coordinates, channel_mask)
        masked_tokens = torch.where(patch_mask.unsqueeze(-1), self.mask_token, tokens)
        contextual, _ = self.attention(masked_tokens, masked_tokens, masked_tokens)
        encoded = contextual + self.encoder(contextual)
        reconstruction = self.reconstruction_head(encoded)
        target = eeg_patches.detach()
        loss = ((reconstruction - target) ** 2)[patch_mask].mean()
        return {"loss": loss, "representations": encoded, "reconstruction": reconstruction}

    def forward(self, eeg_patches, electrode_coordinates, channel_mask):
        tokens = self.tokenize(eeg_patches, electrode_coordinates, channel_mask)
        contextual, _ = self.attention(tokens, tokens, tokens)
        return contextual + self.encoder(contextual)
""",
        encoding="utf-8",
    )
    _write_method_contract(
        tmp_path,
        title,
        [
            {
                "id": "I1",
                "description": "Montage mechanism implementation",
                "evidence": [{"path": "experiments/src/models.py", "symbols": ["MontageAdapter"]}],
            },
            {
                "id": "I2",
                "description": "Masked objective implementation",
                "evidence": [{
                    "path": "experiments/src/models.py",
                    "symbols": ["MaskedEEGFoundationEncoder.masked_pretrain"],
                }],
            },
        ],
        [
            {"idea_mechanism_id": "M1", "implementation_check_ids": ["I1"]},
            {"idea_mechanism_id": "M2", "implementation_check_ids": ["I2"]},
        ],
    )

    gate = WorkflowEngine()._exp_design_method_alignment_gate(
        WorkflowRun(project_path=str(tmp_path)),
        "EEG foundation models",
    )

    assert gate["accepted"] is True, gate
    assert gate["details"]["covered_mechanism_ids"] == ["M1", "M2"]


def test_exp_design_gate_allows_cnn_as_main_method_when_the_idea_declares_it(
    tmp_path: Path,
) -> None:
    title = "Compact Convolutional Foundation Model for Sensor Forecasting"
    _write_selected_idea_contract(
        tmp_path,
        title,
        [{
            "id": "M1",
            "name": "Compact convolutional representation",
            "description": "Use a convolutional representation as the proposed mechanism.",
            "required": True,
        }],
    )
    (tmp_path / "experiments" / "src").mkdir(parents=True)
    (tmp_path / "experiments" / "configs").mkdir()
    (tmp_path / "experiments" / "EXPERIMENT_PLAN.md").write_text(
        f"# Experiment Plan\nAuto-selected idea: {title}\n",
        encoding="utf-8",
    )
    (tmp_path / "experiments" / "configs" / "main.yaml").write_text(
        "model:\n  name: SimpleCNN\n",
        encoding="utf-8",
    )
    (tmp_path / "experiments" / "src" / "models.py").write_text(
        """from torch import nn

class SimpleCNN(nn.Module):
    def __init__(self):
        super().__init__()
        self.encoder = nn.Conv1d(8, 16, 3)

    def forward(self, inputs):
        return self.encoder(inputs)
""",
        encoding="utf-8",
    )
    _write_method_contract(
        tmp_path,
        title,
        [{
            "id": "I1",
            "description": "Declared convolutional mechanism",
            "evidence": [
                {"path": "experiments/src/models.py", "symbols": ["SimpleCNN"]},
                {"path": "experiments/configs/main.yaml", "config_keys": ["model.name"]},
            ],
        }],
        [{"idea_mechanism_id": "M1", "implementation_check_ids": ["I1"]}],
    )

    gate = WorkflowEngine()._exp_design_method_alignment_gate(
        WorkflowRun(project_path=str(tmp_path)),
        "sensor foundation models",
    )

    assert gate["accepted"] is True, gate
    assert gate["details"]["implementation_checks"]["I1"]


def test_method_contract_is_domain_and_language_neutral(tmp_path: Path) -> None:
    title = "Adaptive Acquisition Policy for Catalyst Screening"
    _write_selected_idea_contract(
        tmp_path,
        title,
        [{
            "id": "M1",
            "name": "Adaptive acquisition policy",
            "description": "Select the next candidate from accumulated measurements.",
            "required": True,
        }],
    )
    (tmp_path / "experiments" / "src").mkdir(parents=True)
    (tmp_path / "experiments" / "configs").mkdir()
    (tmp_path / "experiments" / "EXPERIMENT_PLAN.md").write_text(
        f"# Experiment Plan\nAuto-selected idea: {title}\n",
        encoding="utf-8",
    )
    (tmp_path / "experiments" / "configs" / "main.json").write_text(
        json.dumps({"policy": {"name": "adaptive_acquisition"}}),
        encoding="utf-8",
    )
    (tmp_path / "experiments" / "src" / "policy.ts").write_text(
        """export class AdaptiveAcquisitionPolicy {
  selectNext(observations: number[]): number {
    return observations.length;
  }
}
""",
        encoding="utf-8",
    )
    _write_method_contract(
        tmp_path,
        title,
        [{
            "id": "I1",
            "description": "Adaptive policy implementation",
            "evidence": [
                {"path": "experiments/src/policy.ts", "symbols": ["AdaptiveAcquisitionPolicy", "selectNext"]},
                {"path": "experiments/configs/main.json", "config_keys": ["policy.name"]},
            ],
        }],
        [{"idea_mechanism_id": "M1", "implementation_check_ids": ["I1"]}],
    )

    gate = WorkflowEngine()._exp_design_method_alignment_gate(
        WorkflowRun(project_path=str(tmp_path)),
        "catalyst screening",
    )

    assert gate["accepted"] is True, gate


def test_method_contract_rejects_changes_after_idea_acceptance(tmp_path: Path) -> None:
    title = "Invariant Controller Discovery"
    _write_selected_idea_contract(
        tmp_path,
        title,
        [{"id": "M1", "name": "Invariant controller", "description": "Preserve the declared invariant.", "required": True}],
    )
    (tmp_path / "experiments" / "src").mkdir(parents=True)
    (tmp_path / "experiments" / "configs").mkdir()
    (tmp_path / "experiments" / "EXPERIMENT_PLAN.md").write_text(
        f"# Experiment Plan\nAuto-selected idea: {title}\n",
        encoding="utf-8",
    )
    (tmp_path / "experiments" / "src" / "controller.py").write_text(
        "def invariant_controller(state):\n    return state\n",
        encoding="utf-8",
    )
    _write_method_contract(
        tmp_path,
        title,
        [{
            "id": "I1",
            "description": "Controller implementation",
            "evidence": [{"path": "experiments/src/controller.py", "symbols": ["invariant_controller"]}],
        }],
        [{"idea_mechanism_id": "M1", "implementation_check_ids": ["I1"]}],
    )
    accepted, _, idea_details = method_contract_service.validate_selected_idea(tmp_path, title)
    assert accepted
    accepted_hash = idea_details["sha256"]

    idea_path = tmp_path / "ideas" / "SELECTED_IDEA.json"
    changed = json.loads(idea_path.read_text(encoding="utf-8"))
    changed["hypothesis"] = "A different hypothesis introduced after acceptance."
    idea_path.write_text(json.dumps(changed, indent=2), encoding="utf-8")

    valid, issues, _ = method_contract_service.validate_method_contract(
        tmp_path,
        title,
        expected_idea_sha256=accepted_hash,
    )

    assert valid is False
    assert any("changed after the novelty gate" in issue for issue in issues)


def test_research_quality_rejects_file_only_literature(tmp_path: Path) -> None:
    literature = tmp_path / "literature"
    literature.mkdir()
    (literature / "survey.md").write_text("# Survey\nA list of papers.", encoding="utf-8")
    (literature / "references.bib").write_text("@misc{x,title={X}}\n", encoding="utf-8")

    report = research_quality_service.evaluate(str(tmp_path), "lit", "draft", "rigorous")

    assert report["passed"] is False
    assert report["score"] < report["threshold"]
    assert any("coverage too small" in issue for issue in report["issues"])
    assert Path(report["report_path"]).is_file()


def test_research_quality_accepts_critical_evidence_grounded_literature(tmp_path: Path) -> None:
    literature = tmp_path / "literature"
    literature.mkdir()
    (literature / "survey.md").write_text(
        """# Literature Survey

## Search Protocol
We define databases, queries, inclusion criteria, exclusion criteria, and a 2021-2026 time window.

## Theme Taxonomy
The field separates representation learning, transfer, and calibration assumptions.

| Work | Data | Assumption | Evidence | Limitation |
|---|---|---|---|---|
| A | D1 | fixed sensors | transfer gain | narrow cohort |

## Critical Synthesis
The reported findings conflict across datasets and have limitations caused by unmatched protocols.

## Evidence Gap
No study isolates sensor-set shift from parameter-count effects.

## Falsifiable Next Experiment
A grouped split and matched-budget ablation can falsify the proposed mechanism.
""",
        encoding="utf-8",
    )
    bibliography = "\n".join(
        f"@article{{p{index},title={{Paper {index}}},author={{Author}},year={{2025}},url={{https://example.org/{index}}}}}"
        for index in range(8)
    )
    (literature / "references.bib").write_text(bibliography, encoding="utf-8")

    report = research_quality_service.evaluate(str(tmp_path), "lit", "draft", "rigorous")

    assert report["passed"] is True, report
    assert report["score"] >= report["threshold"]
    assert all(item["passed"] for item in report["dimensions"])


def test_results_quality_accepts_structured_metric_run_provenance(
    tmp_path: Path,
) -> None:
    results = tmp_path / "experiments" / "results"
    results.mkdir(parents=True)
    (results / "analysis.md").write_text(
        """# Result Analysis

## Metric provenance and run identity
- simulation_id: cmapss-fd001-1729
- source_run_id: simulation:cmapss-fd001-1729
- manifest: experiments/results/simulated/SIMULATION_MANIFEST.json
- seed: 1729

## Uncertainty
The primary score includes a 95% confidence interval.

## Claim mapping
Claim 1 is supported within the registered benchmark scope.

## Failure analysis
Failure cases and limitations are reported by operating condition.
""",
        encoding="utf-8",
    )

    report = research_quality_service.evaluate(
        str(tmp_path),
        "results",
        "submission",
        "rigorous",
    )
    provenance = next(
        item
        for item in report["dimensions"]
        if item["name"] == "provenance"
    )

    assert report["passed"] is True, report
    assert report["score"] == 1.0
    assert provenance["passed"] is True
    assert "structured:simulation_id" in provenance["matched_patterns"]
    assert "structured:source_run_id" in provenance["matched_patterns"]


def test_results_quality_accepts_standard_uncertainty_and_failure_synonyms(
    tmp_path: Path,
) -> None:
    results = tmp_path / "experiments" / "results"
    results.mkdir(parents=True)
    (results / "analysis.md").write_text(
        """# Evaluation Findings

## Metric lineage
- simulation_id: controlled-study-17
- source_run_id: simulation:controlled-study-17
- artifact: experiments/results/simulated/registered_outcomes.csv

The primary estimate reports a 95% CI and IQR across registered conditions.
Claim C1 maps the declared endpoint to its registered contrast and remains supported only within this controlled evaluation domain.
Residual analysis identifies edge cases and model breakdown under severe shift.
""",
        encoding="utf-8",
    )

    report = research_quality_service.evaluate(
        str(tmp_path),
        "results",
        "submission",
        "rigorous",
    )

    assert report["passed"] is True, report
    assert report["score"] == 1.0


def test_narrative_quality_accepts_domain_facing_synonymous_headings(
    tmp_path: Path,
) -> None:
    (tmp_path / "NARRATIVE_REPORT.md").write_text(
        """# Problem Rationale
The research need follows from a consequential evidence gap.

## Proposed Framework
The architecture uses a personalization mechanism and calibrated predictor.

## Evaluation Findings
Measured observations from the controlled study validate the registered contrast.

## Hypothesis Status
The inference is confirmed within scope and would be refuted under the negative case.

## Boundary Conditions
Applicability is constrained by cohort shift, bias, and external validity risks.
""",
        encoding="utf-8",
    )

    report = research_quality_service.evaluate(
        str(tmp_path),
        "narrative",
        "submission",
        "rigorous",
    )

    assert report["passed"] is True, report
    assert report["score"] == 1.0


def test_results_quality_rejects_seed_and_generic_provenance_words(
    tmp_path: Path,
) -> None:
    results = tmp_path / "experiments" / "results"
    results.mkdir(parents=True)
    (results / "analysis.md").write_text(
        """# Result Analysis

The artifact has provenance evidence and uses fixed seed 1729.
The primary score includes a 95% confidence interval.
Claim 1 is supported within the registered benchmark scope.
Failure cases and limitations are reported by operating condition.
""",
        encoding="utf-8",
    )

    report = research_quality_service.evaluate(
        str(tmp_path),
        "results",
        "submission",
        "rigorous",
    )
    provenance = next(
        item
        for item in report["dimensions"]
        if item["name"] == "provenance"
    )

    assert report["passed"] is False
    assert report["score"] == 0.75
    assert provenance["passed"] is False
    assert provenance["matched_patterns"] == []
    assert any(
        "dimension provenance" in issue
        for issue in report["issues"]
    )


def test_draft_quality_gap_is_advisory_when_core_science_is_present(
    tmp_path: Path,
) -> None:
    ideas = tmp_path / "ideas"
    ideas.mkdir()
    (ideas / "ideas.md").write_text(
        """# Candidate Idea

Problem Anchor: a controlled scientific problem.
Hypothesis: the declared intervention changes the outcome.
Mechanism: the intervention acts through a measurable intermediate variable.
Feasibility: data and compute are available.
""",
        encoding="utf-8",
    )
    base_gate = {
        "accepted": True,
        "verdict_id": "artifact:idea",
        "reviewer": "deterministic:test",
        "summary": "Artifact exists.",
        "details": {},
    }

    draft_gate = research_quality_service.apply_gate(
        dict(base_gate),
        str(tmp_path),
        "idea",
        "draft",
        "rigorous",
    )
    polished_gate = research_quality_service.apply_gate(
        dict(base_gate),
        str(tmp_path),
        "idea",
        "polished",
        "rigorous",
    )

    assert draft_gate["accepted"] is True
    assert draft_gate["warnings"][0]["kind"] == "research_quality"
    assert draft_gate["details"]["research_quality"]["hard_failure"] is False
    assert polished_gate["accepted"] is False


def test_draft_quality_gate_still_blocks_empty_scientific_shell(tmp_path: Path) -> None:
    ideas = tmp_path / "ideas"
    ideas.mkdir()
    (ideas / "ideas.md").write_text("# Ideas\nA feature list only.\n", encoding="utf-8")

    gate = research_quality_service.apply_gate(
        {
            "accepted": True,
            "verdict_id": "artifact:idea",
            "reviewer": "deterministic:test",
            "summary": "Artifact exists.",
            "details": {},
        },
        str(tmp_path),
        "idea",
        "draft",
        "rigorous",
    )

    assert gate["accepted"] is False
    assert gate["details"]["research_quality"]["hard_failure"] is True


@pytest.mark.asyncio
async def test_exp_design_fallback_repairs_existing_shallow_plan(tmp_path: Path, monkeypatch) -> None:
    experiments = tmp_path / "experiments"
    (experiments / "src").mkdir(parents=True)
    (experiments / "configs").mkdir()
    (experiments / "src" / "train.py").write_text("print('check')\n", encoding="utf-8")
    (experiments / "configs" / "main.yaml").write_text("seed: 42\n", encoding="utf-8")
    (experiments / "EXPERIMENT_PLAN.md").write_text(
        "# Experiment Plan\n\nDataset split, baseline, and ablation.\n",
        encoding="utf-8",
    )
    engine = WorkflowEngine()

    async def ignore_event(*_args, **_kwargs):
        return None

    monkeypatch.setattr(engine, "_emit", ignore_event)
    run = WorkflowRun(
        id="depth-repair",
        project_path=str(tmp_path),
        options={"research_quality_mode": "rigorous"},
    )
    await engine._ensure_exp_design_artifacts(
        run,
        "Selected idea: Montage-Stress Geometry-Aware EEG Foundation Model",
        "EEG foundation models",
        assurance="submission",
    )

    plan = (experiments / "EXPERIMENT_PLAN.md").read_text(encoding="utf-8")
    report = research_quality_service.evaluate(
        str(tmp_path), "exp-design", "submission", "rigorous"
    )
    assert "# MERAK Research Depth Contract Supplement" in plan
    assert "Template for `/experiment-bridge`" not in plan
    assert "[Main claim]" not in plan
    assert report["passed"] is True, report
    assert report["score"] == 1.0
    assert all(item["passed"] for item in report["dimensions"])


@pytest.mark.asyncio
async def test_exp_design_scaffold_is_preflight_only_and_not_evidence(tmp_path: Path, monkeypatch) -> None:
    engine = WorkflowEngine()

    async def ignore_event(*_args, **_kwargs):
        return None

    monkeypatch.setattr(engine, "_emit", ignore_event)
    run = WorkflowRun(
        id="scaffold-contract",
        project_path=str(tmp_path),
        options={"research_quality_mode": "rigorous"},
    )
    await engine._ensure_exp_design_artifacts(
        run,
        "Selected idea: robust representation learning",
        "scientific test direction",
        assurance="conference-ready",
    )

    assert not (tmp_path / "experiments/src/train.py").exists()
    blueprint = json.loads((tmp_path / "experiments/IMPLEMENTATION_BLUEPRINT.json").read_text(encoding="utf-8"))
    run_spec = json.loads((tmp_path / "experiments/RUN_SPEC.json").read_text(encoding="utf-8"))
    assert blueprint["schema"] == 1 and blueprint["stages"]
    assert run_spec["implementation_status"] == "implementation_in_progress"
    assert run_spec["execution_status"] == "not_executed"
    assert run_spec["execution_prohibited_in_this_stage"] is True
    assert not (tmp_path / "experiments/results/preflight/scaffold_status.json").exists()
    assert not (tmp_path / "experiments/results/metrics.json").exists()


@pytest.mark.asyncio
async def test_design_only_fallback_does_not_invent_a_domain_metric(
    tmp_path: Path,
    monkeypatch,
) -> None:
    engine = WorkflowEngine()

    async def ignore_event(*_args, **_kwargs):
        return None

    monkeypatch.setattr(engine, "_emit", ignore_event)
    run = WorkflowRun(
        id="planned-config",
        project_path=str(tmp_path),
        options={"run_experiment": False, "research_quality_mode": "rigorous"},
    )
    await engine._ensure_exp_design_artifacts(
        run,
        "Selected idea: a contract-bound project-specific method",
        "scientific test direction",
        assurance="submission",
    )

    config = (tmp_path / "experiments" / "configs" / "main.yaml").read_text(
        encoding="utf-8"
    )
    assert "primary_outcomes: [claim_specific_primary_outcome]" in config
    assert "primary_metric:" not in config
    assert "implementation_status: implementation_in_progress" in config
    assert "primary_metric: macro_f1" not in config
