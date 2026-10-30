"""Review, revision and audit require the same truthful simulation Methods account."""

from server.workflows.review_protocol import ReviewProtocolMixin
from server.workflows.audit_protocol import AuditProtocolMixin
from server.services.narrative_prompt import narrative_authoring_prompt


def test_reviewer_requires_reproducible_scientific_disclosure_without_status_banners():
    prompt = ReviewProtocolMixin._get_reviewer_prompt("medium", "synthetic_preview")
    assert "Methods" in prompt and "生成机制" in prompt and "不能由末尾披露替代" in prompt
    assert "只有在" not in prompt


def test_audit_keeps_generator_methods_and_runtime_ids_distinct():
    prompt = AuditProtocolMixin._evidence_mode_policy("synthetic_preview")
    assert "Methods must explain the actual simulation generator" in prompt
    assert "does not replace the reproducible scientific Methods account" in prompt
    assert "run IDs remain in sidecars" in prompt


def test_narrative_allows_generation_method_in_public_scientific_prose(tmp_path):
    prompt = narrative_authoring_prompt(project_path=str(tmp_path), direction="study",
        options={"non_experiment_evidence_mode": "synthetic_preview"},
        paths={"selected_idea_contract": "idea.json", "novelty_report": "novelty.md"},
        inventory_builder=lambda *_a, **_k: "Existing scientific inputs")
    assert "Explain simulation data generation" in prompt
    assert "generator identity, and evidence-mode labels must not" not in prompt
