from __future__ import annotations

from server.tests._research_quality_and_skills_support import (
    AuditChain as AuditChain,
    AuditResult as AuditResult,
    Path as Path,
    Verdict as Verdict,
    WorkflowEngine as WorkflowEngine,
    WorkflowNode as WorkflowNode,
    WorkflowRun as WorkflowRun,
    asyncio as asyncio,
    invoke_skill as invoke_skill,
    json as json,
    pytest as pytest,
    review_audit_module as review_audit_module,
)


def test_synthetic_audit_accepts_transparent_non_model_warn_fallback(
    tmp_path: Path,
) -> None:
    results = [
        AuditResult(
            layer=layer,
            layer_name=f"Layer {layer}",
            verdict=Verdict.WARN,
            summary="Independent audit transport unavailable; local checks found no blocker.",
            details="deterministic fallback",
            evidence=["paper/main.tex"],
            method="deterministic_fallback",
        )
        for layer in range(1, 6)
    ]
    AuditChain()._save_results(
        results,
        str(tmp_path),
        evidence_mode="synthetic_preview",
        run_id="preview-fallback-audit",
    )

    gate = WorkflowEngine()._audit_acceptance_gate(
        str(tmp_path),
        "submission",
        "",
        evidence_mode="synthetic_preview",
        run_id="preview-fallback-audit",
    )

    assert gate["accepted"] is True, gate
    assert gate["details"]["advisory_verdicts"] == ["WARN"] * 5


def test_proof_checker_invokes_model_and_persists_fresh_provenance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chain = AuditChain()
    paper = tmp_path / "paper" / "main.tex"
    paper.parent.mkdir(parents=True)
    paper.write_text(
        r"""\documentclass{article}
\newtheorem{theorem}{Theorem}
\begin{document}
\begin{theorem}\label{thm:one}For all $x$, $x=x$.\end{theorem}
\begin{proof}Reflexivity.\end{proof}
\end{document}
""",
        encoding="utf-8",
    )

    async def clear(*_args, **_kwargs):
        return AuditResult(
            layer=0,
            layer_name="",
            verdict=Verdict.PASS,
            summary="checked",
            evidence=["paper/main.tex"],
            method="model",
            skill_name="scientific-audit",
            session_id="scientific-session",
            policy_loaded=True,
            model_name="independent-reviewer",
        )

    for name in (
        "_audit_experiment",
        "_audit_result_to_claim",
        "_audit_paper_claims",
        "_audit_citations",
        "_audit_kill_argument",
    ):
        monkeypatch.setattr(chain, name, clear)

    invoked: dict[str, str] = {}
    api_trace = (
        tmp_path / ".merak" / "model-api-reviewer" / "audit-proof-checker-test"
    )
    api_trace.mkdir(parents=True)
    (api_trace / "response.txt").write_text("{}", encoding="utf-8")

    async def invoke(**kwargs):
        invoked["skill_name"] = kwargs["skill_name"]
        invoked["system_prompt"] = kwargs["system_prompt"]
        return (
            json.dumps({
                "audit_skill": "proof-checker",
                "verdict": "PASS",
                "reason_code": "all_proofs_complete",
                "summary": "All detected proof obligations are discharged.",
                "details": {"theorems_audited": 1, "issues": []},
                "evidence": ["paper/main.tex"],
            }),
            "model-api:proof-session",
            "independent-proof-model",
            str(api_trace),
        )

    monkeypatch.setattr(chain, "_invoke_audit_reviewer", invoke)
    results = asyncio.run(
        chain.run_full_audit(
            str(paper),
            str(tmp_path / "experiments"),
            str(tmp_path),
            evidence_mode="executed",
            run_id="proof-run",
        )
    )

    assert invoked["skill_name"] == "proof-checker"
    assert "Loaded independent MERAK skill: /proof-checker" in invoked["system_prompt"]
    assert len(results) == 6
    assert results[5].verdict == Verdict.PASS
    proof = json.loads(
        (tmp_path / "paper" / "PROOF_AUDIT.json").read_text(encoding="utf-8")
    )
    assert proof["audit_skill"] == "proof-checker"
    assert proof["method"] == "model"
    assert proof["session_id"] == "model-api:proof-session"
    assert proof["reviewer_model"] == "independent-proof-model"
    assert proof["audited_input_hashes"]["main.tex"].startswith("sha256:")
    assert (tmp_path / proof["trace_path"] / "response.txt").is_file()


def test_proof_checker_blocking_verdict_blocks_native_audit_gate(
    tmp_path: Path,
) -> None:
    paper = tmp_path / "paper" / "main.tex"
    paper.parent.mkdir(parents=True)
    paper.write_text(
        r"\begin{theorem}False claim.\end{theorem}\begin{proof}Gap.\end{proof}",
        encoding="utf-8",
    )
    trace = tmp_path / ".merak" / "traces" / "proof-checker" / "test_run01"
    trace.mkdir(parents=True)
    for name in ("meta.json", "input.txt", "output.txt"):
        (trace / name).write_text("{}", encoding="utf-8")
    scientific = [
        AuditResult(
            layer=layer,
            layer_name=f"Layer {layer}",
            verdict=Verdict.PASS,
            summary="checked",
            details="inspected",
            evidence=["paper/main.tex"],
            method="model",
            skill_name=review_audit_module.AUDIT_LAYER_SKILLS[layer],
            session_id=f"session-{layer}",
            policy_loaded=True,
            model_name="independent-reviewer",
        )
        for layer in range(1, 6)
    ]
    proof = AuditResult(
        layer=6,
        layer_name="Proof Checker",
        verdict=Verdict.FAIL,
        summary="A critical proof gap remains.",
        details={
            "theorems_audited": 1,
            "issues": [{"id": "T1", "severity": "CRITICAL"}],
        },
        evidence=["paper/main.tex"],
        method="model",
        skill_name="proof-checker",
        session_id="proof-session",
        policy_loaded=True,
        model_name="independent-proof-model",
        reason_code="critical_gap",
        trace_path=trace.relative_to(tmp_path).as_posix(),
    )
    AuditChain()._save_results(
        [*scientific, proof],
        str(tmp_path),
        evidence_mode="executed",
        run_id="blocking-proof-run",
    )

    gate = WorkflowEngine()._audit_acceptance_gate(
        str(tmp_path),
        "submission",
        "",
        evidence_mode="executed",
        run_id="blocking-proof-run",
    )

    assert gate["accepted"] is False
    assert "FAIL" in gate["reason"]
    assert gate["details"]["proof"]["verdict"] == "FAIL"


def test_paper_plan_delegate_timeout_preserves_manual_recovery_without_replacement(
    tmp_path: Path,
    monkeypatch,
) -> None:
    (tmp_path / "paper").mkdir()
    (tmp_path / "NARRATIVE_REPORT.md").write_text(
        "# Narrative\nA bounded contribution with pending evidence.\n",
        encoding="utf-8",
    )

    async def hanging_invoke(*_args, **_kwargs) -> str:
        await asyncio.Event().wait()
        return "unreachable"

    import server.agent.tools as agent_tools

    monkeypatch.setattr(agent_tools, "invoke_skill", hanging_invoke)
    monkeypatch.setattr(
        WorkflowEngine,
        "_agent_node_timeout_seconds",
        staticmethod(lambda *args, **kwargs: 0.01),
    )
    run = WorkflowRun(
        id="paper-plan-timeout",
        project_path=str(tmp_path),
        created_at=1.0,
        options={},
    )

    with pytest.raises(TimeoutError):
        asyncio.run(WorkflowEngine()._execute_stage_delegates(
            node=WorkflowNode(
                id="narrative",
                name="Narrative",
                skill="/research-refine",
            ),
            run=run,
            direction="bounded research",
            effort="balanced",
            assurance="draft",
            opts={"target_venue": "ICLR", "target_pages": 9},
        ))

    plan = tmp_path / "paper" / "PAPER_PLAN.md"
    assert not plan.exists()
    trace = json.loads(
        (tmp_path / ".merak" / "runs" / "paper-plan-timeout.skills.json").read_text(
            encoding="utf-8"
        )
    )
    delegate = trace["stages"]["narrative"]["invocations"][-1]
    assert delegate["skill"] == "paper-plan"
    assert delegate["status"] == "failed"
    assert "idle-time limit" in delegate["error"].lower()
