"""
Agent 工具注册 — IDE 能力暴露给 AI

所有工具都是 IDE 的原生操作能力，Agent 通过 tool_use 调用。
"""

import structlog

from ..engine import agent_engine
from .artifact_tools import (
    evidence_check,
    extract_paper_style,
    figure_manifest,
    overleaf_sync_tool,
    provenance_stamp,
    scaffold_paper_tool,
    threat_scan,
    watchdog_check,
)
from .file_tools import file_edit, file_list, file_read, file_search, file_write
from .document_tools import assemble_document, write_document_part
from .literature_tools import (
    arxiv_search,
    openalex_search,
    pubmed_search,
    web_fetch,
    web_search,
)
from .skill_tool import invoke_skill
from .figure_tool import generate_figure
from .figure_draft_tools import (
    append_figure_svg_fragment,
    begin_figure_svg_draft,
    finalize_figure_svg_draft,
    prepare_model_svg_draft,
    replace_figure_svg_fragment,
    review_figure_svg_composition,
    review_figure_svg_draft,
    submit_model_svg_draft,
    draft_print_diagnostics,
)
from .figure_canvas_tools import (
    append_figure_canvas_primitive,
    finalize_figure_svg_canvas,
    prepare_figure_svg_canvas,
    refresh_figure_canvas_runtime,
    replace_figure_canvas_primitive,
)
from .figure_storyboard_tools import (
    add_figure_storyboard_candidate,
    begin_figure_storyboard,
    select_figure_storyboard,
    submit_figure_storyboard,
)
from .remote_tools import ssh_deploy_experiment, ssh_exec, ssh_sync, terminal_exec
from .review_and_domain_tools import (
    ask_user_question,
    audit_status,
    audit_verdict,
    cross_model_review,
    cross_model_review_reply,
    gemini_search,
    gpu_status,
    latex_compile,
    meta_optimize_propose,
    obsidian_read,
    patent_claims_template,
    patent_prior_art,
    patent_search,
    semantic_scholar_search,
    verify_citation,
    wiki_read,
    wiki_write,
    zotero_search,
)


logger = structlog.get_logger()

__all__ = [
    "arxiv_search", "ask_user_question", "audit_status", "audit_verdict",
    "cross_model_review", "cross_model_review_reply", "evidence_check",
    "extract_paper_style", "figure_manifest", "file_edit", "file_list",
    "file_read", "file_search", "file_write", "assemble_document",
    "write_document_part", "gemini_search",
    "append_figure_svg_fragment", "begin_figure_svg_draft",
    "append_figure_canvas_primitive", "finalize_figure_svg_canvas",
    "prepare_figure_svg_canvas", "replace_figure_canvas_primitive",
    "refresh_figure_canvas_runtime",
    "finalize_figure_svg_draft", "generate_figure", "gpu_status",
    "prepare_model_svg_draft", "submit_model_svg_draft",
    "replace_figure_svg_fragment",
    "review_figure_svg_composition",
    "review_figure_svg_draft",
    "draft_print_diagnostics",
    "add_figure_storyboard_candidate", "begin_figure_storyboard",
    "select_figure_storyboard", "submit_figure_storyboard",
    "invoke_skill", "latex_compile",
    "meta_optimize_propose", "obsidian_read", "openalex_search",
    "overleaf_sync_tool", "patent_claims_template", "patent_prior_art",
    "patent_search", "provenance_stamp", "pubmed_search", "register_all_tools",
    "scaffold_paper_tool", "semantic_scholar_search", "spawn_agent",
    "ssh_deploy_experiment", "ssh_exec", "ssh_sync", "terminal_exec",
    "threat_scan", "verify_citation", "watchdog_check", "web_fetch",
    "web_search", "wiki_read", "wiki_write", "zotero_search",
]


# ==================== 文件操作 ====================

async def spawn_agent(prompt: str, tools: str = "") -> str:
    """启动子 Agent 执行任务

    在当前上下文中创建一个新的 agent session 执行子任务，
    等待完成后返回结果。
    """
    from ..engine import agent_engine
    from .. import ModelRole

    session = agent_engine.create_session(
        system_prompt="You are a research sub-agent. Complete the task and return the result concisely.",
        role=ModelRole.EXECUTOR,
    )
    result = await agent_engine.run(session_id=session.id, user_message=prompt)
    return result


def register_all_tools() -> None:
    """Register the declarative tool surface against the current handlers."""
    from .tool_registration import register_tool_specs

    register_tool_specs(agent_engine, globals())
    logger.info("All agent tools registered", count=len(agent_engine._tools))
