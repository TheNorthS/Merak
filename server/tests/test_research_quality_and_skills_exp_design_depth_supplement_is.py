from __future__ import annotations

from server.tests._research_quality_and_skills_support import (
    AuditChain as AuditChain,
    AuditResult as AuditResult,
    Path as Path,
    Verdict as Verdict,
    WorkflowEngine as WorkflowEngine,
    _audit_results_for_reuse as _audit_results_for_reuse,
    asyncio as asyncio,
    hashlib as hashlib,
    json as json,
    pytest as pytest,
    review_audit_module as review_audit_module,
)


def test_exp_design_depth_supplement_is_derived_from_frozen_contract() -> None:
    supplement = WorkflowEngine._build_exp_design_depth_supplement(
        selected="Catalyst Microstructure Stability",
        research_direction="materials discovery",
        selected_contract={
            "claims": [{
                "id": "C-MAT",
                "statement": "The proposed surface treatment slows grain coarsening.",
            }],
            "mechanisms": [{
                "id": "M-SURFACE",
                "name": "Surface-energy modulation",
                "description": "Changes the coarsening pathway.",
            }],
            "falsification_conditions": [
                "The matched untreated catalyst has the same coarsening rate.",
            ],
        },
        method_contract={
            "claim_evidence_plan": [{
                "idea_claim_id": "C-MAT",
                "outcomes": ["Paired microscopy-derived coarsening rate"],
                "failure_conditions": ["The paired effect does not exceed the null margin"],
            }],
            "evaluation_contract": {
                "comparators_or_controls": ["untreated catalyst", "energy-matched treatment"],
                "component_tests": ["remove the surface treatment"],
                "primary_outcomes": ["coarsening rate"],
                "failure_conditions": ["No effect on the locked endpoint"],
            },
        },
        run_spec={"seeds": [7, 19, 31]},
    )

    assert "C-MAT" in supplement
    assert "Surface-energy modulation" in supplement
    assert "Paired microscopy-derived coarsening rate" in supplement
    assert "untreated catalyst" in supplement
    assert "7, 19, 31" in supplement
    assert "fixed-montage" not in supplement
    assert "channel interpolation" not in supplement


def test_audit_summary_is_console_encoding_safe(tmp_path: Path, monkeypatch) -> None:
    captured: dict[str, str] = {}

    def capture(_event: str, **kwargs) -> None:
        captured.update({key: str(value) for key, value in kwargs.items()})

    monkeypatch.setattr("server.workflows.audit_result_store.logger.info", capture)
    AuditChain()._save_results(
        [AuditResult(layer=1, layer_name="Experiment Audit", verdict=Verdict.FAIL, summary="blocked")],
        str(tmp_path),
    )

    assert captured["summary"] == "BLOCKED"
    assert captured["summary"].isascii()
    payload = json.loads((tmp_path / "audit-results" / "AUDIT_RESULTS.json").read_text(encoding="utf-8"))
    assert payload[0]["verdict"] == "FAIL"


def test_audit_parser_accepts_nested_structured_evidence() -> None:
    parsed = AuditChain()._parse_audit_result(
        """```json
        {
          "verdict": "WARN",
          "summary": "planned evidence remains pending",
          "evidence": [
            {"path": "experiments/results/analysis.md", "status": "checked"}
          ]
        }
        ```"""
    )

    assert parsed.verdict == Verdict.WARN
    assert parsed.summary == "planned evidence remains pending"
    assert parsed.evidence[0]["path"] == "experiments/results/analysis.md"


def test_audit_read_protocol_lists_only_existing_exact_paths(tmp_path: Path) -> None:
    paper = tmp_path / "paper" / "main.tex"
    analysis = tmp_path / "experiments" / "results" / "analysis.md"
    paper.parent.mkdir(parents=True)
    analysis.parent.mkdir(parents=True)
    paper.write_text("paper", encoding="utf-8")
    analysis.write_text("analysis", encoding="utf-8")

    protocol = AuditChain._read_protocol(
        str(tmp_path),
        str(paper),
        str(tmp_path / "experiments"),
    )

    assert str(paper.resolve()) in protocol
    assert str(analysis.resolve()) in protocol
    assert str(tmp_path / "experiments" / "analysis.md") not in protocol
    assert "Never guess shortened paths" in protocol


def test_audit_resume_reuses_successful_same_run_layers_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chain = AuditChain()
    paper = tmp_path / "paper" / "main.tex"
    paper.parent.mkdir(parents=True)
    paper.write_text("\\documentclass{article}", encoding="utf-8")
    calls = {layer: 0 for layer in range(1, 6)}
    skills = {
        1: "experiment-audit",
        2: "result-to-claim",
        3: "paper-claim-audit",
        4: "citation-audit",
        5: "kill-argument",
    }

    def audit_layer(layer: int):
        async def run(*_args, **_kwargs):
            calls[layer] += 1
            if layer == 1 and calls[layer] == 1:
                raise TimeoutError("temporary layer timeout")
            return AuditResult(
                layer=layer,
                layer_name="",
                verdict=Verdict.WARN,
                summary=f"layer {layer} checked",
                method="model",
                skill_name=skills[layer],
                session_id=f"layer-{layer}-session",
                policy_loaded=True,
                model_name="reviewer-model",
            )

        return run

    for name, layer in (
        ("_audit_experiment", 1),
        ("_audit_result_to_claim", 2),
        ("_audit_paper_claims", 3),
        ("_audit_citations", 4),
        ("_audit_kill_argument", 5),
    ):
        monkeypatch.setattr(chain, name, audit_layer(layer))

    with pytest.raises(TimeoutError, match="temporary layer timeout"):
        __import__("asyncio").run(chain.run_full_audit(
            str(paper),
            str(tmp_path / "experiments"),
            str(tmp_path),
            evidence_mode="planned",
            layer_timeout_seconds=1,
            run_id="same-audit-run",
        ))
    second = __import__("asyncio").run(
        chain.run_full_audit(
            str(paper),
            str(tmp_path / "experiments"),
            str(tmp_path),
            evidence_mode="planned",
            layer_timeout_seconds=1,
            run_id="same-audit-run",
        )
    )

    assert all(item.method == "model" for item in second[:5])
    assert second[5].skill_name == "proof-checker"
    assert second[5].verdict == Verdict.NOT_APPLICABLE
    assert second[5].method == "deterministic_detector"
    assert calls == {1: 2, 2: 1, 3: 1, 4: 1, 5: 1}
    build = json.loads(
        (tmp_path / "audit-results" / "AUDIT_BUILD.json").read_text(
            encoding="utf-8"
        )
    )
    assert build["run_id"] == "same-audit-run"
    assert build["schema"] == review_audit_module.AUDIT_BUNDLE_SCHEMA


def test_audit_reuse_rejects_nonaccepted_tampered_and_stale_results(
    tmp_path: Path,
) -> None:
    paper = tmp_path / "paper" / "main.tex"
    paper.parent.mkdir(parents=True)
    paper.write_text(
        "\\documentclass{article}\\begin{document}No theorem.\\end{document}\n",
        encoding="utf-8",
    )
    chain = AuditChain()
    chain._save_results(
        _audit_results_for_reuse({
            1: Verdict.FAIL,
            2: Verdict.ERROR,
            3: Verdict.BLOCKED,
            4: Verdict.WARN,
            5: Verdict.NOT_APPLICABLE,
        }),
        str(tmp_path),
        "planned",
        run_id="reuse-contract",
    )

    reusable = chain._load_reusable_model_results(
        str(tmp_path),
        run_id="reuse-contract",
        evidence_mode="planned",
    )
    assert set(reusable) == {4, 5, 6}
    assert reusable[4].verdict == Verdict.WARN
    assert reusable[5].verdict == Verdict.NOT_APPLICABLE
    assert reusable[6].verdict == Verdict.NOT_APPLICABLE

    results_path = tmp_path / "audit-results" / "AUDIT_RESULTS.json"
    results_path.write_text(
        results_path.read_text(encoding="utf-8") + "\n",
        encoding="utf-8",
    )
    assert chain._load_reusable_model_results(
        str(tmp_path),
        run_id="reuse-contract",
        evidence_mode="planned",
    ) == {}

    chain._save_results(
        _audit_results_for_reuse(),
        str(tmp_path),
        "planned",
        run_id="reuse-contract",
    )
    paper.write_text(
        paper.read_text(encoding="utf-8").replace("No theorem.", "Changed source."),
        encoding="utf-8",
    )
    assert chain._load_reusable_model_results(
        str(tmp_path),
        run_id="reuse-contract",
        evidence_mode="planned",
    ) == {}


def test_proof_semantic_fingerprint_ignores_operational_churn(
    tmp_path: Path,
) -> None:
    paper = tmp_path / "paper" / "main.tex"
    paper.parent.mkdir(parents=True)
    paper.write_text(
        "\\documentclass{article}\n"
        "\\begin{document}\n"
        "\\begin{theorem}A implies B.\\end{theorem}\n"
        "\\begin{proof}By construction.\\end{proof}\n"
        "\\end{document}\n",
        encoding="utf-8",
    )

    def trace(name: str) -> str:
        path = tmp_path / ".merak" / "traces" / "proof-checker" / name
        path.mkdir(parents=True)
        for filename in ("meta.json", "input.txt", "output.txt"):
            (path / filename).write_text(name, encoding="utf-8")
        return path.relative_to(tmp_path).as_posix()

    def proof_result(
        name: str,
        *,
        changed_finding: bool = False,
    ) -> AuditResult:
        note = "The implication omits a boundary case." if changed_finding else "A boundary case is omitted."
        issues = [
            {
                "id": "P-2",
                "severity": "CRITICAL",
                "note": note,
                "timestamp": f"{name}-new",
            },
            {
                "id": "P-1",
                "severity": "MAJOR",
                "note": "  An auxiliary condition is unstated.  ",
                "generated_at": name,
            },
        ]
        if name == "second":
            issues.reverse()
        return AuditResult(
            layer=6,
            layer_name="Proof Checker",
            verdict=Verdict.FAIL,
            summary=f"Operational wording from {name}",
            details={"theorems_audited": 2, "issues": issues},
            evidence=["paper/main.tex:4", "paper/main.tex:3"]
            if name != "second"
            else ["paper/main.tex:3", "paper/main.tex:4"],
            method="model",
            skill_name="proof-checker",
            session_id=f"proof-{name}",
            policy_loaded=True,
            model_name="independent-proof-model",
            reason_code="invalid_step",
            trace_path=trace(name),
        )

    chain = AuditChain()
    scientific = _audit_results_for_reuse()
    chain._save_results(
        [*scientific, proof_result("first")],
        str(tmp_path),
        "executed",
        run_id="proof-semantic-run",
    )
    proof_path = tmp_path / "paper" / "PROOF_AUDIT.json"
    build_path = tmp_path / "audit-results" / "AUDIT_BUILD.json"
    first_bytes = proof_path.read_bytes()
    first_build = json.loads(build_path.read_text(encoding="utf-8"))
    engine = WorkflowEngine()
    first_signature = engine._revision_artifact_signature(
        str(tmp_path),
        "audit",
        {},
    )
    assert 6 not in chain._load_reusable_model_results(
        str(tmp_path),
        run_id="proof-semantic-run",
        evidence_mode="executed",
    )

    chain._save_results(
        [*scientific, proof_result("second")],
        str(tmp_path),
        "executed",
        run_id="proof-semantic-run",
    )
    second_build = json.loads(build_path.read_text(encoding="utf-8"))
    assert proof_path.read_bytes() == first_bytes
    assert second_build["proof_audit_sha256"] == first_build["proof_audit_sha256"]
    assert second_build["proof_semantic_sha256"] == first_build["proof_semantic_sha256"]
    assert engine._revision_artifact_signature(
        str(tmp_path),
        "audit",
        {},
    ) == first_signature

    chain._save_results(
        [*scientific, proof_result("third", changed_finding=True)],
        str(tmp_path),
        "executed",
        run_id="proof-semantic-run",
    )
    third_build = json.loads(build_path.read_text(encoding="utf-8"))
    assert proof_path.read_bytes() != first_bytes
    assert third_build["proof_semantic_sha256"] != first_build["proof_semantic_sha256"]
    assert engine._revision_artifact_signature(
        str(tmp_path),
        "audit",
        {},
    ) != first_signature

    third_semantic_hash = third_build["proof_semantic_sha256"]
    paper.write_text(
        paper.read_text(encoding="utf-8").replace("A implies B", "A strictly implies B"),
        encoding="utf-8",
    )
    chain._save_results(
        [*scientific, proof_result("fourth", changed_finding=True)],
        str(tmp_path),
        "executed",
        run_id="proof-semantic-run",
    )
    fourth_build = json.loads(build_path.read_text(encoding="utf-8"))
    assert fourth_build["proof_semantic_sha256"] != third_semantic_hash

    tampered = json.loads(proof_path.read_text(encoding="utf-8"))
    tampered["details"]["issues"][0]["note"] = "tampered proof finding"
    proof_path.write_text(
        json.dumps(tampered, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    fourth_build["proof_audit_sha256"] = hashlib.sha256(
        proof_path.read_bytes()
    ).hexdigest()
    build_path.write_text(
        json.dumps(fourth_build, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    issues, _ = review_audit_module.validate_proof_audit_artifact(
        tmp_path,
        run_id="proof-semantic-run",
        evidence_mode="executed",
    )
    assert any("semantic fingerprint" in issue for issue in issues)


def test_audit_bundle_uses_build_as_atomic_commit_marker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paper = tmp_path / "paper" / "main.tex"
    paper.parent.mkdir(parents=True)
    paper.write_text("\\documentclass{article}\n", encoding="utf-8")
    chain = AuditChain()
    writes: list[str] = []
    real_atomic_write = review_audit_module.atomic_write_json

    def tracking_write(path, payload, **kwargs):
        writes.append(Path(path).name)
        return real_atomic_write(path, payload, **kwargs)

    monkeypatch.setattr(review_audit_module, "atomic_write_json", tracking_write)
    results = _audit_results_for_reuse()
    chain._save_results(
        results,
        str(tmp_path),
        "planned",
        run_id="atomic-audit-run",
    )
    assert writes[-1] == "AUDIT_BUILD.json"
    assert writes.index("AUDIT_RESULTS.json") < writes.index("AUDIT_BUILD.json")
    assert writes.index("PROOF_AUDIT.json") < writes.index("AUDIT_BUILD.json")

    results_path = tmp_path / "audit-results" / "AUDIT_RESULTS.json"
    proof_path = tmp_path / "paper" / "PROOF_AUDIT.json"
    build_path = tmp_path / "audit-results" / "AUDIT_BUILD.json"
    build = json.loads(build_path.read_text(encoding="utf-8"))
    assert build["results_sha256"] == hashlib.sha256(results_path.read_bytes()).hexdigest()
    assert build["proof_audit_sha256"] == hashlib.sha256(proof_path.read_bytes()).hexdigest()

    old_build = build_path.read_bytes()

    def fail_commit(path, payload, **kwargs):
        if Path(path) == build_path:
            raise RuntimeError("commit marker unavailable")
        return real_atomic_write(path, payload, **kwargs)

    monkeypatch.setattr(review_audit_module, "atomic_write_json", fail_commit)
    changed = _audit_results_for_reuse()
    changed[0].summary = "new scientific finding"
    with pytest.raises(RuntimeError, match="commit marker unavailable"):
        chain._save_results(
            changed,
            str(tmp_path),
            "planned",
            run_id="atomic-audit-run",
        )
    assert build_path.read_bytes() == old_build
    assert chain._load_reusable_model_results(
        str(tmp_path),
        run_id="atomic-audit-run",
        evidence_mode="planned",
    ) == {}


def test_audit_build_records_strict_layer_runtime_contract(
    tmp_path: Path,
) -> None:
    paper = tmp_path / "paper" / "main.tex"
    paper.parent.mkdir(parents=True)
    paper.write_text(
        "\\documentclass{article}\\begin{document}No theorem.\\end{document}\n",
        encoding="utf-8",
    )
    AuditChain()._save_results(
        _audit_results_for_reuse(),
        str(tmp_path),
        "planned",
        run_id="strict-audit-contract",
    )

    validation = review_audit_module.validate_audit_bundle(
        tmp_path,
        run_id="strict-audit-contract",
        evidence_mode="planned",
    )
    build = validation["build"]

    assert validation["valid"] is True, validation["issues"]
    assert validation["accepted"] is True
    assert build["schema"] == review_audit_module.AUDIT_BUNDLE_SCHEMA
    assert build["status"] == "complete"
    assert build["audit_runtime_signature"]
    assert build["reviewer_route_sha256"]
    assert sorted(item["layer"] for item in build["layer_contracts"]) == [
        1, 2, 3, 4, 5, 6,
    ]
    for contract in build["layer_contracts"]:
        layer = contract["layer"]
        assert contract["skill_name"] == review_audit_module.AUDIT_LAYER_SKILLS[layer]
        assert contract["policy_sha256"] == review_audit_module.audit_policy_sha256(
            contract["skill_name"]
        )
        assert contract["audit_runtime_signature"] == build["audit_runtime_signature"]
        assert contract["reviewer_route_sha256"] == build["reviewer_route_sha256"]


@pytest.mark.parametrize(
    ("changed_contract", "expected_issue"),
    [
        ("policy", "policy provenance is missing or stale"),
        ("runtime", "audit runtime signature is missing or stale"),
        ("route", "audit reviewer route is missing or stale"),
    ],
)
def test_audit_reuse_rejects_changed_policy_runtime_or_route(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    changed_contract: str,
    expected_issue: str,
) -> None:
    paper = tmp_path / "paper" / "main.tex"
    paper.parent.mkdir(parents=True)
    paper.write_text("\\documentclass{article}\n", encoding="utf-8")
    chain = AuditChain()
    chain._save_results(
        _audit_results_for_reuse(),
        str(tmp_path),
        "planned",
        run_id="changed-audit-contract",
    )

    if changed_contract == "policy":
        real_policy_hash = review_audit_module.audit_policy_sha256

        def changed_policy(skill_name: str) -> str:
            if skill_name == "experiment-audit":
                return "0" * 64
            return real_policy_hash(skill_name)

        monkeypatch.setattr(
            review_audit_module,
            "audit_policy_sha256",
            changed_policy,
        )
    elif changed_contract == "runtime":
        real_runtime = review_audit_module.audit_runtime_attestation

        def changed_runtime() -> dict:
            payload = dict(real_runtime())
            payload["signature"] = "0" * 64
            return payload

        monkeypatch.setattr(
            review_audit_module,
            "audit_runtime_attestation",
            changed_runtime,
        )
    else:
        real_route = review_audit_module.audit_reviewer_route

        def changed_route(**kwargs) -> dict:
            payload = json.loads(json.dumps(real_route(**kwargs)))
            payload["reviewer"]["model_identity"] += "-changed"
            return payload

        monkeypatch.setattr(
            review_audit_module,
            "audit_reviewer_route",
            changed_route,
        )

    validation = review_audit_module.validate_audit_bundle(
        tmp_path,
        run_id="changed-audit-contract",
        evidence_mode="planned",
    )

    assert validation["valid"] is False
    assert any(expected_issue in issue for issue in validation["issues"])
    assert chain._load_reusable_model_results(
        str(tmp_path),
        run_id="changed-audit-contract",
        evidence_mode="planned",
    ) == {}


@pytest.mark.parametrize(
    ("artifact", "expected_issue"),
    [
        ("results", "AUDIT_RESULTS.json does not match AUDIT_BUILD.json"),
        ("proof", "PROOF_AUDIT.json does not match AUDIT_BUILD.json"),
        ("build", "AUDIT_RESULTS.json does not match AUDIT_BUILD.json"),
    ],
)
def test_validate_audit_bundle_rejects_artifact_tampering(
    tmp_path: Path,
    artifact: str,
    expected_issue: str,
) -> None:
    paper = tmp_path / "paper" / "main.tex"
    paper.parent.mkdir(parents=True)
    paper.write_text("\\documentclass{article}\n", encoding="utf-8")
    chain = AuditChain()
    chain._save_results(
        _audit_results_for_reuse(),
        str(tmp_path),
        "planned",
        run_id="tamper-audit-contract",
    )
    results_path = tmp_path / "audit-results" / "AUDIT_RESULTS.json"
    proof_path = tmp_path / "paper" / "PROOF_AUDIT.json"
    build_path = tmp_path / "audit-results" / "AUDIT_BUILD.json"
    if artifact == "results":
        results_path.write_bytes(results_path.read_bytes() + b"\n")
    elif artifact == "proof":
        proof_path.write_bytes(proof_path.read_bytes() + b"\n")
    else:
        build = json.loads(build_path.read_text(encoding="utf-8"))
        build["results_sha256"] = "0" * 64
        build_path.write_text(json.dumps(build, indent=2), encoding="utf-8")

    validation = review_audit_module.validate_audit_bundle(
        tmp_path,
        run_id="tamper-audit-contract",
        evidence_mode="planned",
    )

    assert validation["valid"] is False
    assert expected_issue in validation["issues"]
    assert chain._load_reusable_model_results(
        str(tmp_path),
        run_id="tamper-audit-contract",
        evidence_mode="planned",
    ) == {}


def test_audit_source_change_during_run_does_not_commit_bundle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paper = tmp_path / "paper" / "main.tex"
    paper.parent.mkdir(parents=True)
    paper.write_text("\\documentclass{article}\n", encoding="utf-8")
    chain = AuditChain()

    def audit_layer(layer: int):
        async def run(*_args, **_kwargs):
            if layer == 5:
                paper.write_text(
                    "\\documentclass{article}\n% changed during audit\n",
                    encoding="utf-8",
                )
            return _audit_results_for_reuse()[layer - 1]

        return run

    for name, layer in (
        ("_audit_experiment", 1),
        ("_audit_result_to_claim", 2),
        ("_audit_paper_claims", 3),
        ("_audit_citations", 4),
        ("_audit_kill_argument", 5),
    ):
        monkeypatch.setattr(chain, name, audit_layer(layer))

    with pytest.raises(
        review_audit_module.AuditSourceChangedError,
        match="source bundle changed",
    ):
        asyncio.run(
            chain.run_full_audit(
                str(paper),
                str(tmp_path / "experiments"),
                str(tmp_path),
                evidence_mode="planned",
                run_id="source-change-audit",
            )
        )

    assert not (tmp_path / "audit-results" / "AUDIT_BUILD.json").exists()


def test_audit_consumers_share_bundle_contract_failures(
    tmp_path: Path,
) -> None:
    from server.services.workflow_readiness import workflow_readiness_service

    paper = tmp_path / "paper" / "main.tex"
    paper.parent.mkdir(parents=True)
    paper.write_text("\\documentclass{article}\n", encoding="utf-8")
    chain = AuditChain()
    chain._save_results(
        _audit_results_for_reuse(),
        str(tmp_path),
        "planned",
        run_id="consumer-contract",
    )
    build_path = tmp_path / "audit-results" / "AUDIT_BUILD.json"
    build = json.loads(build_path.read_text(encoding="utf-8"))
    build["audit_runtime_signature"] = "0" * 64
    build_path.write_text(json.dumps(build, indent=2), encoding="utf-8")

    validation = review_audit_module.validate_audit_bundle(
        tmp_path,
        run_id="consumer-contract",
        evidence_mode="planned",
    )
    readiness_issues, _, readiness_attestation = (
        workflow_readiness_service._audit_issues(
            tmp_path,
            run_id="consumer-contract",
            evidence_mode="planned",
        )
    )
    gate = WorkflowEngine()._audit_acceptance_gate(
        str(tmp_path),
        "submission",
        "",
        evidence_mode="planned",
        run_id="consumer-contract",
    )
    shared_issue = "audit runtime signature is missing or stale"

    assert shared_issue in validation["issues"]
    assert shared_issue in readiness_issues
    assert shared_issue in gate["details"]["issues"]
    assert readiness_attestation["valid"] is False
    assert gate["accepted"] is False
    assert chain._load_reusable_model_results(
        str(tmp_path),
        run_id="consumer-contract",
        evidence_mode="planned",
    ) == {}


def test_planned_audit_preserves_layer_timeout_for_manual_resume(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chain = AuditChain()

    async def slow(*_args, **_kwargs):
        raise TimeoutError("temporary reviewer timeout")

    async def clear(*_args, **_kwargs):
        return AuditResult(layer=0, layer_name="", verdict=Verdict.PASS, summary="checked")

    monkeypatch.setattr(chain, "_audit_experiment", slow)
    for name in ("_audit_result_to_claim", "_audit_paper_claims", "_audit_citations", "_audit_kill_argument"):
        monkeypatch.setattr(chain, name, clear)

    with pytest.raises(TimeoutError, match="temporary reviewer timeout"):
        __import__("asyncio").run(chain.run_full_audit(
            str(tmp_path / "paper.tex"),
            str(tmp_path / "experiments"),
            str(tmp_path),
            evidence_mode="planned",
            layer_timeout_seconds=1,
        ))
    assert not (tmp_path / "audit-results/AUDIT_BUILD.json").exists()


def test_planned_audit_preserves_parse_failure_for_manual_resume(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chain = AuditChain()

    async def malformed(*_args, **_kwargs):
        return chain._parse_audit_result("unstructured reviewer prose")

    async def clear(*_args, **_kwargs):
        return AuditResult(layer=0, layer_name="", verdict=Verdict.PASS, summary="checked")

    monkeypatch.setattr(chain, "_audit_kill_argument", malformed)
    for name in ("_audit_experiment", "_audit_result_to_claim", "_audit_paper_claims", "_audit_citations"):
        monkeypatch.setattr(chain, name, clear)
    monkeypatch.setattr(
        "server.services.node_risk_audit.node_risk_audit_service.audit_node",
        lambda *_args, **_kwargs: {"findings": []},
    )

    with pytest.raises(RuntimeError, match="Resume this layer"):
        __import__("asyncio").run(chain.run_full_audit(
            str(tmp_path / "paper.tex"),
            str(tmp_path / "experiments"),
            str(tmp_path),
            evidence_mode="synthetic_preview",
            layer_timeout_seconds=1,
        ))
    assert not (tmp_path / "audit-results/AUDIT_BUILD.json").exists()


def test_audit_fallback_preserves_selected_non_experiment_evidence_mode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[dict] = []

    def clear_audit(_project_path, _node_id, options, *, persist=False):
        captured.append(dict(options))
        assert persist is False
        return {"findings": []}

    monkeypatch.setattr(
        "server.services.node_risk_audit.node_risk_audit_service.audit_node",
        clear_audit,
    )

    result = AuditChain._deterministic_fallback(
        1,
        "Experiment Audit",
        str(tmp_path),
        TimeoutError(),
        evidence_mode="synthetic_preview",
    )

    assert captured
    assert all(
        item["non_experiment_evidence_mode"] == "synthetic_preview"
        for item in captured
    )
    assert result.verdict == Verdict.WARN


def test_submission_audit_warns_are_advisory_in_all_evidence_modes(
    tmp_path: Path,
) -> None:
    warning_results = [
        AuditResult(
            layer=layer,
            layer_name=f"Layer {layer}",
            verdict=Verdict.WARN,
            summary="Pending empirical evidence.",
            details="inspected evidence",
            method="model",
            skill_name=review_audit_module.AUDIT_LAYER_SKILLS[layer],
            session_id=f"audit-session-{layer}",
            policy_loaded=True,
            model_name="independent-reviewer",
        )
        for layer in range(1, 6)
    ]
    engine = WorkflowEngine()

    AuditChain()._save_results(
        warning_results,
        str(tmp_path),
        evidence_mode="synthetic_preview",
        run_id="preview-audit",
    )
    preview = engine._audit_acceptance_gate(
        str(tmp_path),
        "submission",
        "",
        evidence_mode="synthetic_preview",
        run_id="preview-audit",
    )

    AuditChain()._save_results(
        warning_results,
        str(tmp_path),
        evidence_mode="executed",
        run_id="executed-audit",
    )
    executed = engine._audit_acceptance_gate(
        str(tmp_path),
        "submission",
        "",
        evidence_mode="executed",
        run_id="executed-audit",
    )

    assert preview["accepted"] is True, preview
    assert executed["accepted"] is True, executed
    assert executed["warnings"][0]["warning_count"] == 5
    assert executed["details"]["advisory_verdicts"] == ["WARN"] * 5
    assert executed["details"]["proof"]["verdict"] == "NOT_APPLICABLE"
