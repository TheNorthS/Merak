"""Resolve feature switches consistently for owners and delegated skills."""


def disabled_workflow_tools(options: dict | None = None) -> set[str]:
    options = options or {}
    # The workflow owns pull-before-review and push-after-compile; a model must
    # not issue a second sync or publish before those gates have completed.
    disabled = {"overleaf_sync"}
    features = {
        "enable_gemini": {"mcp__gemini-cli__search"},
        "enable_zotero": {"mcp__zotero__search"},
        "enable_obsidian": {"mcp__obsidian-vault__read"},
        "enable_meta_optimization": {"meta_optimize_propose"},
        "enable_patent_search": {"patent_search", "patent_prior_art", "patent_claims_template"},
    }
    for feature, tools in features.items():
        if not options.get(feature, feature == "enable_gemini"):
            disabled.update(tools)
    return disabled


def delegated_disabled_tools(project_path: str) -> set[str]:
    from ..agent.skill_resume import workflow_scope
    from ..workflows.run_state import RunState

    run_id, _ = workflow_scope.get()
    if not run_id:
        return set()
    state = RunState(project_path, run_id).load()
    if not state:
        raise ValueError("Cannot establish delegated workflow capabilities without durable run state")
    options = (state.get("config") or {}).get("options") or {}
    return disabled_workflow_tools(options)
