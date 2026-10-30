"""An old compilable deck is not a complete current talk delivery."""

from server.services.slide_authoring_contract import SUPPORT_FILES, talk_delivery_findings, loaded_talk_instruction


def test_missing_talk_outputs_and_short_deck_remain_blocking(tmp_path):
    findings = talk_delivery_findings(tmp_path, '\\begin{frame}content\\end{frame}\n' * 12)
    assert {item['id'] for item in findings} == {'PPT-TALK-FRAMES', 'PPT-TALK-SUPPORT'}
    assert all(item['severity'] == 'blocker' for item in findings)


def test_complete_authored_contract_preserves_the_paper_and_excludes_comment_frames(tmp_path):
    slides = tmp_path/'slides';slides.mkdir()
    for name in SUPPORT_FILES:(slides/name).write_text('Paper-grounded authored talk material')
    text = '\\begin{frame}content\\end{frame}\n' * 16 + '% \\begin{frame}comment\n' * 20
    assert talk_delivery_findings(tmp_path, text) == []
    assert 'do not call Skill(paper-talk)' in loaded_talk_instruction()
    assert 'continue directly' in loaded_talk_instruction()
    assert 'synthetic' in loaded_talk_instruction()


def test_real_workflow_policy_allows_required_talk_files_but_protects_upstream(tmp_path):
    from types import SimpleNamespace
    from server.agent.engine import AgentEngine
    from server.agent import ToolCall
    from server.contracts.registry import workflow_artifact_contracts
    engine = AgentEngine(SimpleNamespace(_providers={}, _strategy={}))
    session = engine.create_session()
    session.project_path = str(tmp_path)
    session.tool_policy = 'workflow_artifacts'
    session.workflow_node_id = 'ppt'
    for name in SUPPORT_FILES:
        relative = 'slides/' + name
        assert relative in workflow_artifact_contracts['ppt'].required
        call = ToolCall('write-' + name, 'Write', {'path': relative, 'content': 'Paper-grounded talk text'})
        assert engine._apply_tool_policy(session, call) is None
    blocked = engine._apply_tool_policy(session, ToolCall('wrong', 'Write', {
        'path': 'paper/sections/03_method.tex', 'content': 'Unauthorized change'}))
    assert blocked is not None and not blocked.success
