from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest

from server.agent.engine import agent_engine
from server.api.workflow import WorkflowRunRequest
from server.services.node_risk_audit import node_risk_audit_service
from server.services.method_contract import method_contract_service
from server.workflows.engine import (
    LITERATURE_SOURCE_TOOLS,
    WorkflowEngine,
    WorkflowNode,
    WorkflowRun,
    NodeStatus,
)


def _options(*sources: str, **extra) -> dict:
    return {
        "research_strategy": {"literature_sources": list(sources)},
        **extra,
    }


@pytest.mark.parametrize(
    "options",
    [
        {"run_experiment": True},
        {
            "run_experiment": False,
            "non_experiment_evidence_mode": "synthetic_preview",
        },
    ],
)
def test_every_default_node_input_builder_executes_for_primary_evidence_modes(
    tmp_path: Path,
    options: dict,
) -> None:
    engine = WorkflowEngine()
    ideas = tmp_path / "ideas"
    ideas.mkdir()
    ideas.joinpath("SELECTED_IDEA.json").write_text(json.dumps({
        "schema": 2, "status": "accepted", "title": "Runtime smoke test",
        "problem_statement": "A bounded workflow smoke contract.",
        "hypothesis": "The declared mechanism changes a measurable outcome.",
        "claims": [{
            "id": "C1", "statement": "A measurable claim.",
            "publication_statement": "A measurable claim.",
        }],
        "mechanisms": [{
            "id": "M1", "name": "Bounded mechanism",
            "description": "A current-schema mechanism.", "required": True,
            "publication_name": "Bounded mechanism",
            "publication_description": "A current-schema mechanism.",
            "publication_evaluation": "Matched outcome comparison.",
        }],
        "falsification_conditions": ["Reject C1 when the outcome does not change."],
        "publication": {
            "language": "en",
            "title": "Runtime smoke test",
            "method_name": "Bounded method",
            "contribution_type": "objective_mechanism",
            "comparator_names": ["Bounded method", "Matched control"],
        },
    }), encoding="utf-8")
    experiments = tmp_path / "experiments"
    experiments.mkdir()
    experiments.joinpath("EXPERIMENT_PLAN.md").write_text(
        "# Experiment Plan\n\nRuntime smoke test\n",
        encoding="utf-8",
    )
    assert method_contract_service.ensure_planned_method_contract(tmp_path)
    nodes = engine._get_default_nodes()
    run = WorkflowRun(
        project_path=str(tmp_path),
        nodes=nodes,
        options=options,
    )

    for node in nodes:
        message = engine._build_node_input(node, "runtime smoke test", run)
        assert isinstance(message, str) and message.strip(), node.id


def test_workflow_request_rejects_unknown_or_empty_literature_sources() -> None:
    with pytest.raises(ValueError, match="unknown literature source"):
        WorkflowRunRequest(
            node_ids=["lit"],
            project_path=".",
            literature_sources=["arxiv", "made_up_database"],
        )


def test_focused_node_inputs_are_bounded_and_reach_the_node_prompt(
    tmp_path: Path,
) -> None:
    request = WorkflowRunRequest(
        node_ids=["lit"],
        project_path=str(tmp_path),
        node_inputs={"max_papers": 18, "databases": ["arxiv", "openalex"]},
    )
    engine = WorkflowEngine()
    node = next(item for item in engine._get_default_nodes() if item.id == "lit")
    run = WorkflowRun(
        project_path=str(tmp_path),
        nodes=[node],
        options={"node_inputs": request.node_inputs},
    )

    prompt = engine._build_node_input(node, "bounded node-input test", run)

    assert '"max_papers": 18' in prompt
    assert '"openalex"' in prompt
    assert "do not override frozen upstream contracts" in prompt.casefold()

    with pytest.raises(ValueError, match="32 KiB"):
        WorkflowRunRequest(
            node_ids=["lit"],
            project_path=str(tmp_path),
            node_inputs={"query": "x" * (33 * 1024)},
        )
    with pytest.raises(ValueError, match="at least one source"):
        WorkflowRunRequest(
            node_ids=["lit"],
            project_path=".",
            literature_sources=[],
        )


def test_selected_sources_enable_exact_search_tools_and_hide_unselected_tools() -> None:
    engine = WorkflowEngine()
    options = _options("arxiv", "semantic_scholar")
    contract = engine._literature_source_tool_contract("lit", options)
    assert contract == {
        "arxiv": "arxiv_search",
        "semantic_scholar": "semantic_scholar_search",
    }

    candidate_tools = [*LITERATURE_SOURCE_TOOLS.values(), "WebFetch", "Read"]
    enabled = engine._filter_literature_source_tools(
        "lit",
        options,
        candidate_tools,
    )
    assert "arxiv_search" in enabled
    assert "semantic_scholar_search" in enabled
    assert "WebFetch" in enabled
    assert "WebSearch" not in enabled
    assert "mcp__gemini-cli__search" not in enabled
    assert "mcp__zotero__search" not in enabled
    assert engine._search_tool_result_succeeded(True, "[paper] result") is True
    assert engine._search_tool_result_succeeded(True, "S2 API error: 429") is False
    assert engine._search_tool_result_succeeded(
        True,
        "No search API configured. Set EXA_API_KEY.",
    ) is False


def test_openalex_and_pubmed_are_first_class_audited_sources() -> None:
    engine = WorkflowEngine()
    engine._ensure_agent_tools()
    options = _options("openalex", "pubmed")

    assert engine._literature_source_tool_contract("lit", options) == {
        "openalex": "openalex_search",
        "pubmed": "pubmed_search",
    }
    enabled = engine._filter_literature_source_tools(
        "lit",
        options,
        [*LITERATURE_SOURCE_TOOLS.values(), "WebFetch", "Read"],
    )
    assert "openalex_search" in enabled
    assert "pubmed_search" in enabled
    assert "arxiv_search" not in enabled
    assert "semantic_scholar_search" not in enabled
    assert "WebFetch" in enabled


def test_all_default_nodes_have_registered_required_runtime_tools(tmp_path: Path) -> None:
    engine = WorkflowEngine()
    engine._ensure_agent_tools()
    registered = set(agent_engine._tools)
    options = _options(
        "arxiv",
        "semantic_scholar",
        "openalex",
        "pubmed",
        "web",
        "gemini",
        "zotero",
        "obsidian",
        run_experiment=True,
        gpu_target="remote",
        enable_patent_search=True,
        enable_gpt_image=True,
        enable_overleaf_sync=True,
    )
    plan = SimpleNamespace(specialists=[])
    nodes = engine._get_default_nodes()
    assert [node.id for node in nodes] == [
        "lit", "idea", "novelty", "exp-design", "exp-run", "results",
        "narrative", "figure", "paper", "review", "audit", "compile", "ppt",
    ]
    for node in nodes:
        required = engine._workflow_stage_required_tools(
            node,
            str(tmp_path),
            plan,
            options,
        )
        assert required <= registered, f"{node.id}: {sorted(required - registered)}"

    local_tools = engine._workflow_stage_required_tools(
        WorkflowNode(id="exp-run", name="Experiment", skill="/experiment-bridge"),
        str(tmp_path),
        plan,
        {"run_experiment": True, "gpu_target": "local"},
    )
    assert not {"ssh_exec", "ssh_deploy", "ssh_sync", "watchdog_check"} & local_tools


def test_retired_image2_tools_are_not_registered_or_required(
    tmp_path: Path,
) -> None:
    engine = WorkflowEngine()
    engine._ensure_agent_tools()
    retired_tools = {
        "mcp__codex-image2__generate",
        "mcp__codex-image2__generate_start",
        "mcp__codex-image2__generate_status",
        "mcp__codex-image2__finalize",
        "mcp__codex-image2__verify",
    }
    assert not (retired_tools & set(agent_engine._tools))
    node = WorkflowNode(
        id="figure",
        name="Figures",
        skill="/figure-spec",
    )
    plan = SimpleNamespace(specialists=[])

    required = engine._workflow_stage_required_tools(
        node,
        str(tmp_path),
        plan,
        {"illustration_mode": "auto", "enable_gpt_image": False},
    )
    assert not (retired_tools & required)
    assert not (retired_tools & engine._workflow_disabled_tools({
        "illustration_mode": "auto",
        "enable_gpt_image": True,
    }))


def test_runtime_search_evidence_accumulates_attempts_and_drives_gate(tmp_path: Path) -> None:
    strategy = {"literature_sources": ["arxiv", "semantic_scholar"]}
    strategy_path = tmp_path / ".merak" / "research_strategy.json"
    strategy_path.parent.mkdir(parents=True)
    strategy_path.write_text(
        json.dumps({"run_id": "run-1", "strategy": strategy}),
        encoding="utf-8",
    )
    options = {"research_strategy": strategy}
    run = WorkflowRun(
        id="run-1",
        project_path=str(tmp_path),
        options=options,
    )
    node = WorkflowNode(id="lit", name="Literature", skill="/research-lit")
    engine = WorkflowEngine()

    path = engine._persist_search_evidence(
        run,
        node,
        options,
        ["arxiv_search", "semantic_scholar_search"],
        [
            {"tool": "arxiv_search", "args": {"query": "topic"}, "success": True},
            {
                "tool": "semantic_scholar_search",
                "args": {"query": "topic"},
                "success": False,
                "output_preview": "S2 API error: 429",
            },
        ],
    )
    assert path is not None
    payload = json.loads(path.read_text(encoding="utf-8"))
    usage = payload["stages"]["lit"]["source_usage"]
    assert usage["arxiv"]["status"] == "used"
    assert usage["semantic_scholar"]["status"] == "failed"
    findings = node_risk_audit_service._search_evidence_findings(
        tmp_path,
        "lit",
        options,
    )
    assert any(
        item["id"] == "LIT-SOURCE-004" and item["severity"] == "warning"
        for item in findings
    )

    engine._persist_search_evidence(
        run,
        node,
        options,
        ["arxiv_search", "semantic_scholar_search"],
        [{"tool": "semantic_scholar_search", "success": True}],
    )
    assert node_risk_audit_service._search_evidence_findings(
        tmp_path,
        "lit",
        options,
    ) == []


def test_runtime_search_evidence_serializes_concurrent_stage_attempts(
    tmp_path: Path,
) -> None:
    strategy = {"literature_sources": ["arxiv"]}
    options = {"research_strategy": strategy}
    run = WorkflowRun(id="concurrent-search", project_path=str(tmp_path), options=options)
    node = WorkflowNode(id="lit", name="Literature", skill="/research-lit")
    engine = WorkflowEngine()
    barrier = threading.Barrier(2)

    def persist(query: str) -> None:
        barrier.wait()
        engine._persist_search_evidence(
            run,
            node,
            options,
            ["arxiv_search"],
            [{
                "tool": "arxiv_search",
                "args": {"query": query},
                "success": True,
            }],
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(persist, query) for query in ("first", "second")]
        for future in futures:
            future.result(timeout=10)

    project_payload = json.loads(
        (tmp_path / "literature" / "SEARCH_EVIDENCE.json").read_text(
            encoding="utf-8"
        )
    )
    runtime_payload = json.loads(
        (
            tmp_path
            / ".merak"
            / "runs"
            / "concurrent-search.search-evidence.json"
        ).read_text(encoding="utf-8")
    )
    attempts = project_payload["stages"]["lit"]["attempts"]
    assert len(attempts) == 2
    assert {
        attempt["calls"][0]["args"]["query"] for attempt in attempts
    } == {"first", "second"}
    assert runtime_payload == project_payload
    assert not list(tmp_path.rglob("*.tmp"))
    assert not list(tmp_path.rglob("*.lock"))


def test_subset_run_restores_matching_search_provenance_without_new_retrieval(
    tmp_path: Path,
) -> None:
    engine = WorkflowEngine()
    strategy = engine._normalize_research_strategy({
        "literature_year_from": 2019,
        "literature_year_to": 2026,
        "literature_sources": ["arxiv", "semantic_scholar", "web"],
    })
    (tmp_path / "literature").mkdir(parents=True)
    (tmp_path / ".merak" / "runs").mkdir(parents=True)
    (tmp_path / "literature" / "SEARCH_EVIDENCE.json").write_text(
        json.dumps({
            "run_id": "retrieval-run",
            "selected_sources": strategy["literature_sources"],
            "stages": {},
        }),
        encoding="utf-8",
    )
    (tmp_path / ".merak" / "runs" / "retrieval-run.json").write_text(
        json.dumps({
            "config": {"options": {"research_strategy": strategy}},
        }),
        encoding="utf-8",
    )
    engine._save_research_strategy(tmp_path, "unrelated-subset-run", strategy)

    restored = engine._restore_search_strategy_provenance(tmp_path, strategy)

    assert restored == "retrieval-run"
    payload = json.loads(
        (tmp_path / ".merak" / "research_strategy.json").read_text(encoding="utf-8")
    )
    assert payload["run_id"] == "retrieval-run"

    changed = {**strategy, "literature_year_from": 2020}
    assert engine._restore_search_strategy_provenance(tmp_path, changed) == ""



def test_search_failure_classifier_distinguishes_platform_and_request_errors() -> None:
    engine = WorkflowEngine()
    assert engine._search_tool_failure_kind(True, "Search failed: ") == "retrieval_failure"
    assert engine._search_tool_failure_kind(True, "arXiv API error: 429") == "platform_unavailable"
    assert engine._search_tool_failure_kind(False, "ReadError: peer closed") == "platform_unavailable"
    assert engine._search_tool_failure_kind(True, "arXiv query error: empty query") == "request_invalid"
    assert engine._search_tool_failure_kind(True, "[paper] result") == ""


def test_saving_identical_research_strategy_is_content_idempotent(tmp_path: Path) -> None:
    engine = WorkflowEngine()
    strategy = {
        "literature_sources": ["arxiv", "semantic_scholar"],
        "literature_year_from": 2021,
    }
    engine._save_research_strategy(tmp_path, "same-run", strategy)
    path = tmp_path / ".merak" / "research_strategy.json"
    first = path.read_bytes()

    engine._save_research_strategy(tmp_path, "same-run", strategy)

    assert path.read_bytes() == first


def test_unknown_empty_search_failure_requires_diagnosis(tmp_path: Path) -> None:
    strategy = {
        "literature_sources": ["arxiv", "semantic_scholar", "web"],
    }
    state = tmp_path / ".merak" / "research_strategy.json"
    state.parent.mkdir(parents=True)
    state.write_text(
        json.dumps({"run_id": "legacy-run", "strategy": strategy}),
        encoding="utf-8",
    )
    evidence_path = tmp_path / "literature" / "SEARCH_EVIDENCE.json"
    evidence_path.parent.mkdir(parents=True)
    evidence_path.write_text(
        json.dumps({
            "run_id": "legacy-run",
            "selected_sources": strategy["literature_sources"],
            "stages": {
                "novelty": {
                    "attempts": [{
                        "calls": [
                            {
                                "source": "arxiv",
                                "success": False,
                                "output_preview": "Search failed: ",
                            },
                            {"source": "semantic_scholar", "success": True},
                            {"source": "web", "success": True},
                        ],
                    }],
                    "source_usage": {
                        "arxiv": {"status": "failed"},
                        "semantic_scholar": {"status": "used"},
                        "web": {"status": "used"},
                    },
                },
            },
        }),
        encoding="utf-8",
    )

    findings = node_risk_audit_service._search_evidence_findings(
        tmp_path,
        "novelty",
        {"research_strategy": strategy},
    )

    assert any(
        item["id"] == "NOV-SOURCE-003" and item["severity"] == "blocker"
        for item in findings
    )
    assert not any(item["id"] == "NOV-SOURCE-004" for item in findings)


def test_web_only_does_not_replace_failed_structured_source(tmp_path: Path) -> None:
    strategy = {"literature_sources": ["arxiv", "web"]}
    state = tmp_path / ".merak" / "research_strategy.json"
    state.parent.mkdir(parents=True)
    state.write_text(
        json.dumps({"run_id": "web-only-run", "strategy": strategy}),
        encoding="utf-8",
    )
    evidence_path = tmp_path / "literature" / "SEARCH_EVIDENCE.json"
    evidence_path.parent.mkdir(parents=True)
    evidence_path.write_text(
        json.dumps({
            "run_id": "web-only-run",
            "stages": {
                "novelty": {
                    "attempts": [{
                        "calls": [
                            {
                                "source": "arxiv",
                                "success": False,
                                "failure_kind": "platform_unavailable",
                                "output_preview": "arXiv API error: 429",
                            },
                            {"source": "web", "success": True},
                        ],
                    }],
                    "source_usage": {
                        "arxiv": {"status": "failed"},
                        "web": {"status": "used"},
                    },
                },
            },
        }),
        encoding="utf-8",
    )

    findings = node_risk_audit_service._search_evidence_findings(
        tmp_path,
        "novelty",
        {"research_strategy": strategy},
    )

    assert any(
        item["id"] == "NOV-SOURCE-003" and item["severity"] == "blocker"
        for item in findings
    )

def test_search_evidence_keeps_non_transient_or_total_failure_blocking(
    tmp_path: Path,
) -> None:
    strategy = {"literature_sources": ["arxiv", "semantic_scholar"]}
    state = tmp_path / ".merak" / "research_strategy.json"
    state.parent.mkdir(parents=True)
    state.write_text(
        json.dumps({"run_id": "run-blocked", "strategy": strategy}),
        encoding="utf-8",
    )
    options = {"research_strategy": strategy}
    engine = WorkflowEngine()
    run = WorkflowRun(id="run-blocked", project_path=str(tmp_path), options=options)
    node = WorkflowNode(id="lit", name="Literature", skill="/research-lit")
    engine._persist_search_evidence(
        run,
        node,
        options,
        ["arxiv_search", "semantic_scholar_search"],
        [
            {"tool": "arxiv_search", "success": False, "output_preview": "HTTP 429"},
            {"tool": "semantic_scholar_search", "success": False, "output_preview": "HTTP 503"},
        ],
    )
    findings = node_risk_audit_service._search_evidence_findings(
        tmp_path,
        "lit",
        options,
    )
    assert any(
        item["id"] == "LIT-SOURCE-003" and item["severity"] == "blocker"
        for item in findings
    )


def test_runtime_search_evidence_recovers_after_model_overwrite(tmp_path: Path) -> None:
    options = _options("arxiv")
    run = WorkflowRun(id="runtime-evidence", project_path=str(tmp_path), options=options)
    node = WorkflowNode(id="novelty", name="Novelty", skill="/novelty-check")
    engine = WorkflowEngine()
    path = engine._persist_search_evidence(
        run,
        node,
        options,
        ["arxiv_search"],
        [{
            "tool": "arxiv_search",
            "args": {"query": "claim-level novelty"},
            "success": True,
            "output_preview": "paper result",
        }],
    )
    assert path is not None
    runtime_path = tmp_path / ".merak" / "runs" / "runtime-evidence.search-evidence.json"
    assert runtime_path.is_file()

    path.write_text(
        json.dumps({"schema": 1, "model_claim": "tools were used"}),
        encoding="utf-8",
    )
    engine._persist_search_evidence(
        run,
        node,
        options,
        ["arxiv_search"],
        [],
    )

    restored = json.loads(path.read_text(encoding="utf-8"))
    assert restored["run_id"] == run.id
    assert restored["stages"]["novelty"]["complete"] is True
    assert restored["stages"]["novelty"]["source_usage"]["arxiv"]["calls"] == 1


@pytest.mark.asyncio
async def test_novelty_preflight_executes_each_missing_selected_source_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = WorkflowEngine()
    engine._ensure_agent_tools()
    options = {
        "research_strategy": {
            "literature_sources": ["arxiv", "semantic_scholar", "web"],
            "literature_year_from": 2020,
            "literature_year_to": 2026,
            "literature_max_papers": 15,
        },
    }
    run = WorkflowRun(
        id="novelty-preflight",
        project_path=str(tmp_path),
        options=options,
    )
    node = WorkflowNode(id="novelty", name="Novelty", skill="/novelty-check")
    calls: list[tuple[str, str, int]] = []

    def handler(source: str):
        async def search(query: str, max_results: int = 0) -> str:
            calls.append((source, query, max_results))
            return f"{source} structured result"
        return search

    monkeypatch.setitem(agent_engine._tools, "arxiv_search", handler("arxiv"))
    monkeypatch.setitem(
        agent_engine._tools,
        "semantic_scholar_search",
        handler("semantic_scholar"),
    )
    monkeypatch.setitem(agent_engine._tools, "WebSearch", handler("web"))

    async def noop(*_args, **_kwargs) -> None:
        return None

    monkeypatch.setattr(engine, "_emit", noop)

    context = await engine._ensure_stage_search_evidence(
        run,
        node,
        "EEG foundation models",
        options,
        ["arxiv_search", "semantic_scholar_search", "WebSearch"],
    )

    assert [item[0] for item in calls] == ["arxiv", "semantic_scholar", "web"]
    assert all("2020 2026" in item[1] for item in calls)
    assert all(item[2] == 8 for item in calls)
    assert "Platform" not in context
    evidence_path = tmp_path / "literature" / "SEARCH_EVIDENCE.json"
    payload = json.loads(evidence_path.read_text(encoding="utf-8"))
    assert payload["stages"]["novelty"]["complete"] is True
    assert all(
        item["status"] == "used"
        for item in payload["stages"]["novelty"]["source_usage"].values()
    )

    await engine._ensure_stage_search_evidence(
        run,
        node,
        "EEG foundation models",
        options,
        ["arxiv_search", "semantic_scholar_search", "WebSearch"],
    )
    assert len(calls) == 3


def test_literature_and_novelty_skills_declare_structured_search_tools() -> None:
    root = Path(__file__).resolve().parents[2] / "merak-skills"
    for skill in ("research-lit", "novelty-check"):
        content = (root / skill / "SKILL.md").read_text(encoding="utf-8")
        assert "arxiv_search" in content
        assert "semantic_scholar_search" in content


def test_meta_optimization_observes_quality_gate_pauses() -> None:
    node = WorkflowNode(
        id="novelty",
        name="Novelty",
        skill="/novelty-check",
        status=NodeStatus.IDLE,
    )
    run = WorkflowRun(id="run-meta", nodes=[node])
    state = {
        "phases": {
            "novelty": {
                "status": "awaiting_revision",
                "details": {
                    "revision": {
                        "last_gate": {
                            "summary": "Selected idea contract is incomplete",
                            "issues": ["missing hypothesis", "missing falsification"],
                        },
                    },
                },
            },
        },
    }
    candidates = WorkflowEngine._meta_optimization_candidates(run, state)
    assert len(candidates) == 1
    assert candidates[0].id == "novelty"
    assert "missing hypothesis" in str(candidates[0].error)
