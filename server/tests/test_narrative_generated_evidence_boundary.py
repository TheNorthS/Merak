"""Generated record identity cannot force scientific support or falsification."""

from server.services.narrative_prompt import narrative_authoring_prompt


def test_synthetic_table_track_preserves_observations_without_forcing_scientific_verdict():
    prompt = narrative_authoring_prompt(project_path="fixture", direction="research",
        options={"non_experiment_evidence_mode":"synthetic_preview"},
        paths={"selected_idea_contract":"idea.json","novelty_report":"novelty.md"},
        inventory_builder=lambda *a,**k:"existing source list")
    assert "哈希绑定只证明记录身份" in prompt
    assert "允许科学主张保持待验证" in prompt
    assert "不得仅因没有物理实验" not in prompt
