from __future__ import annotations

from server.tests._node_risk_audit_support import (
    AuditChain as AuditChain,
    AuditResult as AuditResult,
    CrossModelReviewer as CrossModelReviewer,
    Path as Path,
    ReviewRound as ReviewRound,
    ReviewState as ReviewState,
    Verdict as Verdict,
    _write_json as _write_json,
    json as json,
    node_risk_audit_service as node_risk_audit_service,
    os as os,
    proof_source_bundle as proof_source_bundle,
    pytest as pytest,
    time as time,
)


def test_table_assets_are_not_required_in_the_figure_manifest(tmp_path: Path) -> None:
    _write_json(
        tmp_path / "figures" / "FIGURE_MANIFEST.json",
        {"schema": 1, "figures": []},
    )
    _write_json(
        tmp_path / "figures" / "SCIENTIFIC_ASSET_PLAN.json",
        {
            "schema": 1,
            "assets": [
                {
                    "id": "experimental_design_matrix",
                    "kind": "table",
                    "scientific_role": "experimental_design",
                }
            ],
        },
    )

    findings = node_risk_audit_service._audit_figure(
        tmp_path,
        {"run_experiment": False},
    )

    assert not any(item["id"] == "FIG-PLAN-002" for item in findings)


def test_figure_quality_finding_targets_the_editable_asset_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from server.services.figure_artifacts import figure_artifact_registry

    payload = {
        "schema": 1,
        "figures": [
            {
                "id": "evaluation_design",
                "source_path": "figures/evaluation_design.mmd",
                "output_path": "figures/evaluation_design.pdf",
                "metadata": {"semantic_key": "evaluation_design"},
            }
        ],
    }
    monkeypatch.setattr(
        figure_artifact_registry,
        "validate",
        lambda _path: (True, [], payload),
    )
    monkeypatch.setattr(
        figure_artifact_registry,
        "scientific_quality_issues",
        lambda _path: [
            "evaluation_design: mermaid node ledger needs 5 text lines; paper limit is 4"
        ],
    )
    monkeypatch.setattr(
        figure_artifact_registry,
        "scientific_alignment_issues",
        lambda _path: [],
    )

    findings = node_risk_audit_service._audit_figure(tmp_path, {})
    finding = next(item for item in findings if item["id"] == "FIG-QUALITY-001")

    assert finding["asset_ids"] == ["evaluation_design"]
    assert "figures/evaluation_design.mmd" in finding["target_files"]


def test_review_risk_audit_requires_substantive_rounds(tmp_path: Path) -> None:
    _write_json(
        tmp_path / "review-stage" / "REVIEW_STATE.json",
        {"final_score": 9, "final_verdict": "ready", "rounds": []},
    )

    report = node_risk_audit_service.audit_node(tmp_path, "review", {})

    assert report["blocking"] is True
    assert any(item["id"] == "REVIEW-STATE-002" for item in report["findings"])


def test_empty_managed_review_still_reports_stale_source_hash(
    tmp_path: Path,
) -> None:
    for relative, content in (
        (
            "paper/main.tex",
            "\\documentclass{article}\\begin{document}new\\end{document}",
        ),
        ("ideas/SELECTED_IDEA.json", "{}"),
        ("experiments/results/analysis.md", "new analysis"),
        ("figures/SCIENTIFIC_ASSET_PLAN.json", "{}"),
        ("figures/FIGURE_MANIFEST.json", "{}"),
    ):
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    _write_json(
        tmp_path / "review-stage" / "REVIEW_STATE.json",
        {
            "managed_by": "cross_model_review_loop",
            "source_bundle_sha256": "stale-source-bundle",
            "current_round": 1,
            "max_rounds": 4,
            "rounds": [],
        },
    )

    report = node_risk_audit_service.audit_node(tmp_path, "review", {})
    finding_ids = {item["id"] for item in report["findings"]}

    assert "REVIEW-STATE-002" in finding_ids
    assert "REVIEW-HASH-001" in finding_ids


def test_ready_review_may_close_with_no_remaining_weaknesses_or_actions(
    tmp_path: Path,
) -> None:
    _write_json(
        tmp_path / "review-stage" / "REVIEW_STATE.json",
        {
            "current_round": 1,
            "max_rounds": 1,
            "bounded_complete": True,
            "final_score": 8,
            "final_verdict": "ready",
            "evidence_mode": "planned",
            "publication_ready": False,
            "executor_model": "writer",
            "reviewer_model": "reviewer",
            "rounds": [
                {
                    "round": 1,
                    "score": 8,
                    "verdict": "ready",
                    "strengths": ["All prior objections were resolved."],
                    "weaknesses": [],
                    "action_items": [],
                }
            ],
        },
    )

    findings = node_risk_audit_service._audit_review(
        tmp_path,
        {"run_experiment": False},
    )

    assert not any(item["id"] == "REVIEW-STATE-003" for item in findings)


def test_planned_review_cannot_claim_publication_readiness(tmp_path: Path) -> None:
    _write_json(
        tmp_path / "review-stage" / "REVIEW_STATE.json",
        {
            "final_score": 7,
            "final_verdict": "almost",
            "evidence_mode": "planned",
            "publication_ready": True,
            "executor_model": "writer",
            "reviewer_model": "reviewer",
            "rounds": [
                {
                    "round": 1,
                    "weaknesses": ["Experiments remain pending."],
                    "action_items": [
                        "Run the registered experiments before submission."
                    ],
                }
            ],
        },
    )

    report = node_risk_audit_service.audit_node(
        tmp_path,
        "review",
        {"run_experiment": False},
        persist=False,
    )

    assert any(item["id"] == "REVIEW-MODE-002" for item in report["findings"])
    assert report["blocking"] is True


def test_complete_simulation_requires_valid_outcome_but_keeps_early_parse_warning(
    tmp_path: Path,
) -> None:
    _write_json(
        tmp_path / "review-stage" / "REVIEW_STATE.json",
        {
            "current_round": 3,
            "max_rounds": 3,
            "bounded_complete": True,
            "threshold_met": False,
            "final_score": 4,
            "final_verdict": "needs_work",
            "evidence_mode": "synthetic_preview",
            "publication_ready": False,
            "executor_model": "writer",
            "reviewer_model": "reviewer",
            "rounds": [
                {
                    "round": 1,
                    "score": 5,
                    "verdict": "needs_work",
                    "weaknesses": ["Unable to parse structured review"],
                    "action_items": [],
                },
                {
                    "round": 2,
                    "score": 5,
                    "verdict": "needs_work",
                    "weaknesses": ["Protocol remains underspecified."],
                    "action_items": ["Specify the protocol."],
                },
                {
                    "round": 3,
                    "score": 4,
                    "verdict": "needs_work",
                    "weaknesses": ["Experiments remain pending."],
                    "action_items": ["Run experiments before submission."],
                },
            ],
        },
    )

    findings = node_risk_audit_service._audit_review(
        tmp_path,
        {
            "run_experiment": False,
            "non_experiment_evidence_mode": "synthetic_preview",
        },
    )

    severities = {item["id"]: item["severity"] for item in findings}
    # The complete simulation track uses the same review quality threshold as
    # other complete evidence tracks; an earlier parser fallback is still only
    # advisory when the final structured round is valid.
    assert [item["id"] for item in findings if item["severity"] == "blocker"] == [
        "REVIEW-OUTCOME-001",
    ]
    assert severities["REVIEW-PARSE-001"] == "warning"
    assert severities["REVIEW-OUTCOME-001"] == "blocker"


def test_final_review_parse_failure_remains_blocking_in_preview_mode(
    tmp_path: Path,
) -> None:
    _write_json(
        tmp_path / "review-stage" / "REVIEW_STATE.json",
        {
            "current_round": 2,
            "max_rounds": 2,
            "bounded_complete": True,
            "final_score": 5,
            "final_verdict": "needs_work",
            "evidence_mode": "synthetic_preview",
            "rounds": [
                {
                    "round": 1,
                    "weaknesses": ["One valid objection."],
                    "action_items": ["Address it."],
                },
                {
                    "round": 2,
                    "weaknesses": ["Unable to parse structured review"],
                    "action_items": [],
                },
            ],
        },
    )

    findings = node_risk_audit_service._audit_review(
        tmp_path,
        {
            "run_experiment": False,
            "non_experiment_evidence_mode": "synthetic_preview",
        },
    )

    assert any(
        item["id"] == "REVIEW-PARSE-001" and item["severity"] == "blocker"
        for item in findings
    )


def test_five_layer_audit_requires_coverage_and_inspected_evidence(
    tmp_path: Path,
) -> None:
    _write_json(
        tmp_path / "audit-results" / "AUDIT_RESULTS.json",
        [
            {
                "layer": layer,
                "layer_name": f"Layer {layer}",
                "verdict": "PASS",
                "summary": "checked",
                "evidence": [f"artifact-{layer}"],
            }
            for layer in range(1, 6)
        ],
    )
    clear = node_risk_audit_service._audit_audit(tmp_path, {})
    assert not any(item["severity"] == "blocker" for item in clear)

    payload = json.loads(
        (tmp_path / "audit-results" / "AUDIT_RESULTS.json").read_text(encoding="utf-8")
    )
    payload.pop()
    payload[0]["evidence"] = []
    _write_json(tmp_path / "audit-results" / "AUDIT_RESULTS.json", payload)
    blocked = node_risk_audit_service._audit_audit(tmp_path, {})
    ids = {item["id"] for item in blocked}
    assert "AUDIT-LAYER-001" in ids
    assert "AUDIT-EVID-001" in ids


def test_audit_error_is_never_treated_as_a_pass(tmp_path: Path) -> None:
    _write_json(
        tmp_path / "audit-results" / "AUDIT_RESULTS.json",
        [
            {
                "layer": layer,
                "layer_name": f"Layer {layer}",
                "verdict": "ERROR" if layer == 4 else "PASS",
                "summary": "codec failure" if layer == 4 else "checked",
                "evidence": [f"artifact-{layer}"],
            }
            for layer in range(1, 6)
        ],
    )

    findings = node_risk_audit_service._audit_audit(tmp_path, {})

    assert any(item["id"] == "AUDIT-ERROR-004" for item in findings)
    assert any(
        item["id"] == "AUDIT-ERROR-004" and item["severity"] == "blocker"
        for item in findings
    )


def test_audit_evidence_mode_must_match_workflow_mode(tmp_path: Path) -> None:
    _write_json(
        tmp_path / "audit-results" / "AUDIT_RESULTS.json",
        [
            {
                "layer": layer,
                "layer_name": f"Layer {layer}",
                "verdict": "PASS",
                "summary": "checked",
                "evidence": [f"artifact-{layer}"],
                "evidence_mode": "executed",
            }
            for layer in range(1, 6)
        ],
    )

    findings = node_risk_audit_service._audit_audit(
        tmp_path,
        {"run_experiment": False},
    )

    assert any(item["id"] == "AUDIT-MODE-001" for item in findings)


def test_append_only_execution_events_do_not_invalidate_a_completed_audit(
    tmp_path: Path,
) -> None:
    audit_path = tmp_path / "audit-results" / "AUDIT_RESULTS.json"
    _write_json(
        audit_path,
        [
            {
                "layer": layer,
                "layer_name": f"Layer {layer}",
                "verdict": "PASS",
                "summary": "checked",
                "evidence": [f"artifact-{layer}"],
                "evidence_mode": "planned",
            }
            for layer in range(1, 6)
        ],
    )
    old = time.time() - 60
    os.utime(audit_path, (old, old))
    events = tmp_path / ".merak" / "execution_events.jsonl"
    events.parent.mkdir(parents=True)
    events.write_text('{"tool":"Bash","success":true}\n', encoding="utf-8")

    findings = node_risk_audit_service._audit_audit(
        tmp_path,
        {"run_experiment": False},
    )
    assert not any(item["id"] == "AUDIT-STALE-001" for item in findings)

    metrics = tmp_path / "experiments" / "results" / "metrics.csv"
    metrics.parent.mkdir(parents=True)
    metrics.write_text("run_id,metric\nr1,0.5\n", encoding="utf-8")
    findings = node_risk_audit_service._audit_audit(
        tmp_path,
        {"run_experiment": False},
    )
    assert any(item["id"] == "AUDIT-STALE-001" for item in findings)


def test_review_and_audit_become_stale_when_figure_manifest_changes(
    tmp_path: Path,
) -> None:
    _write_json(
        tmp_path / "review-stage" / "REVIEW_STATE.json",
        {
            "rounds": [
                {
                    "round": 1,
                    "weaknesses": ["Check figure evidence."],
                    "action_items": ["Keep claim maturity visible."],
                }
            ],
            "final_score": 7,
            "final_verdict": "almost",
            "evidence_mode": "planned",
            "publication_ready": False,
            "executor_model": "writer",
            "reviewer_model": "reviewer",
        },
    )
    _write_json(
        tmp_path / "audit-results" / "AUDIT_RESULTS.json",
        [
            {
                "layer": layer,
                "layer_name": f"Layer {layer}",
                "verdict": "PASS",
                "summary": "checked",
                "evidence": ["figures/FIGURE_MANIFEST.json"],
                "evidence_mode": "planned",
            }
            for layer in range(1, 6)
        ],
    )
    for relative, content in (
        ("paper/main.tex", "paper"),
        ("ideas/SELECTED_IDEA.json", "{}"),
        ("experiments/results/analysis.md", "pending"),
        ("figures/SCIENTIFIC_ASSET_PLAN.json", "{}"),
        ("figures/FIGURE_MANIFEST.json", "{}"),
    ):
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    old = time.time() - 30
    review_path = tmp_path / "review-stage" / "REVIEW_STATE.json"
    audit_path = tmp_path / "audit-results" / "AUDIT_RESULTS.json"
    os.utime(review_path, (old, old))
    os.utime(audit_path, (old, old))

    review_ids = {
        item["id"]
        for item in node_risk_audit_service._audit_review(
            tmp_path,
            {"run_experiment": False},
        )
    }
    audit_ids = {
        item["id"]
        for item in node_risk_audit_service._audit_audit(
            tmp_path,
            {"run_experiment": False},
        )
    }

    assert "REVIEW-STALE-001" in review_ids
    assert "AUDIT-STALE-001" in audit_ids


def test_review_and_audit_hashes_detect_content_change_with_old_mtime(
    tmp_path: Path,
) -> None:
    for relative, content in (
        (
            "paper/main.tex",
            "\\documentclass{article}\\begin{document}paper\\end{document}",
        ),
        ("ideas/SELECTED_IDEA.json", "{}"),
        ("experiments/results/analysis.md", "pending analysis"),
        ("experiments/EXPERIMENT_PLAN.md", "frozen plan"),
        ("figures/SCIENTIFIC_ASSET_PLAN.json", "{}"),
        ("figures/FIGURE_MANIFEST.json", "{}"),
        ("NARRATIVE_REPORT.md", "bounded narrative"),
    ):
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    review_state = ReviewState(
        run_id="hash-review",
        rounds=[
            ReviewRound(
                round_number=1,
                score=7,
                verdict="almost",
                weaknesses=["Experiments remain pending."],
                action_items=["Run the registered experiments."],
            )
        ],
        current_round=1,
        max_rounds=3,
        final_score=7,
        final_verdict="almost",
        is_complete=True,
        executor_model="writer",
        reviewer_model="reviewer",
        evidence_mode="planned",
        publication_ready=False,
    )
    CrossModelReviewer()._save_state(review_state, str(tmp_path))
    paper = tmp_path / "paper" / "main.tex"
    paper.write_text(
        "\\documentclass{article}\\begin{document}changed paper\\end{document}",
        encoding="utf-8",
    )
    old = time.time() - 60
    os.utime(paper, (old, old))

    review_ids = {
        item["id"]
        for item in node_risk_audit_service._audit_review(
            tmp_path,
            {"run_experiment": False},
        )
    }
    assert "REVIEW-HASH-001" in review_ids
    assert "REVIEW-STALE-001" not in review_ids

    AuditChain()._save_results(
        [
            AuditResult(
                layer=layer,
                layer_name=f"Layer {layer}",
                verdict=Verdict.PASS,
                summary="checked",
                evidence=["paper/main.tex"],
            )
            for layer in range(1, 6)
        ],
        str(tmp_path),
        evidence_mode="planned",
    )
    plan = tmp_path / "experiments" / "EXPERIMENT_PLAN.md"
    plan.write_text("changed frozen plan", encoding="utf-8")
    os.utime(plan, (old, old))

    audit_ids = {
        item["id"]
        for item in node_risk_audit_service._audit_audit(
            tmp_path,
            {"run_experiment": False},
        )
    }
    assert "AUDIT-HASH-002" in audit_ids
    assert "AUDIT-STALE-001" not in audit_ids


def test_audit_hash_attestation_survives_copy_mtime_changes(
    tmp_path: Path,
) -> None:
    plan = tmp_path / "experiments" / "EXPERIMENT_PLAN.md"
    plan.parent.mkdir(parents=True)
    plan.write_text("frozen experiment plan", encoding="utf-8")
    AuditChain()._save_results(
        [
            AuditResult(
                layer=layer,
                layer_name=f"Layer {layer}",
                verdict=Verdict.PASS,
                summary="checked",
                evidence=["experiments/EXPERIMENT_PLAN.md"],
            )
            for layer in range(1, 6)
        ],
        str(tmp_path),
        evidence_mode="planned",
    )
    audit_path = tmp_path / "audit-results" / "AUDIT_RESULTS.json"
    later = audit_path.stat().st_mtime + 30
    os.utime(plan, (later, later))

    findings = node_risk_audit_service._audit_audit(
        tmp_path,
        {"run_experiment": False},
    )
    ids = {item["id"] for item in findings}

    assert "AUDIT-STALE-001" not in ids
    assert "AUDIT-HASH-002" not in ids
    assert "AUDIT-HASH-003" not in ids


def test_audit_counterevidence_routes_to_the_responsible_upstream_stage(
    tmp_path: Path,
) -> None:
    _write_json(
        tmp_path / "audit-results" / "AUDIT_RESULTS.json",
        [
            {
                "layer": layer,
                "layer_name": f"Layer {layer}",
                "verdict": "FAIL" if layer == 3 else "PASS",
                "summary": "paper claim is unsupported" if layer == 3 else "checked",
                "evidence": [f"artifact-{layer}"],
            }
            for layer in range(1, 6)
        ],
    )

    findings = node_risk_audit_service._audit_audit(tmp_path, {})
    routed = [item for item in findings if item["id"] == "AUDIT-FAIL-003"]

    assert len(routed) == 1
    assert routed[0]["upstream_node"] == "paper"
    assert routed[0]["severity"] == "blocker"


def test_stale_managed_audit_does_not_replay_old_failure_owner(
    tmp_path: Path,
) -> None:
    paper = tmp_path / "paper" / "main.tex"
    paper.parent.mkdir(parents=True)
    paper.write_text("\\documentclass{article}\nold\n", encoding="utf-8")
    AuditChain()._save_results(
        [
            AuditResult(
                layer=layer,
                layer_name=f"Layer {layer}",
                verdict=(Verdict.FAIL if layer == 1 else Verdict.PASS),
                summary=("old result failure" if layer == 1 else "checked"),
                evidence=["paper/main.tex"],
                method="model",
                skill_name={
                    1: "experiment-audit",
                    2: "result-to-claim",
                    3: "paper-claim-audit",
                    4: "citation-audit",
                    5: "kill-argument",
                }[layer],
                session_id=f"session-{layer}",
                policy_loaded=True,
                model_name="reviewer",
            )
            for layer in range(1, 6)
        ],
        str(tmp_path),
        evidence_mode="planned",
        run_id="stale-managed-audit",
    )
    paper.write_text("\\documentclass{article}\nnew\n", encoding="utf-8")

    findings = node_risk_audit_service._audit_audit(
        tmp_path,
        {"run_experiment": False},
    )
    ids = {item["id"] for item in findings}

    assert "AUDIT-HASH-002" in ids
    assert "AUDIT-FAIL-001" not in ids


@pytest.mark.parametrize(
    ("layer", "summary", "evidence", "expected_owner"),
    [
        (
            1,
            "Runtime manifest records a failed training job.",
            [".merak/experiments/run-1/run.json"],
            "exp-run",
        ),
        (
            2,
            "The manuscript overclaims support beyond the measured result.",
            ["paper/sections/05_results.tex"],
            "paper",
        ),
        (
            3,
            "The research synthesis no longer matches the accepted plan.",
            ["paper/PAPER_PLAN.md"],
            "narrative",
        ),
        (
            4,
            "A retained citation has no traceable source.",
            ["literature/references.bib"],
            "lit",
        ),
        (
            5,
            "The figure encodes the wrong scientific comparison.",
            ["figures/main_comparison.png"],
            "figure",
        ),
        (
            5,
            "The proof audit build hash is missing.",
            ["paper/PROOF_AUDIT.json"],
            "audit",
        ),
        (
            5,
            "A counterexample exposes an invalid proof.",
            ["paper/PROOF_AUDIT.json", "paper/sections/03_method.tex"],
            "paper",
        ),
    ],
)
def test_audit_failure_owner_uses_evidence_and_category(
    tmp_path: Path,
    layer: int,
    summary: str,
    evidence: list[str],
    expected_owner: str,
) -> None:
    _write_json(
        tmp_path / "audit-results" / "AUDIT_RESULTS.json",
        [
            {
                "layer": candidate,
                "layer_name": f"Layer {candidate}",
                "verdict": "FAIL" if candidate == layer else "PASS",
                "summary": summary if candidate == layer else "checked",
                "details": "inspected",
                "evidence": evidence if candidate == layer else ["paper/main.tex"],
            }
            for candidate in range(1, 6)
        ],
    )

    findings = node_risk_audit_service._audit_audit(tmp_path, {})
    routed = next(item for item in findings if item["id"] == f"AUDIT-FAIL-{layer:03d}")

    assert routed["upstream_node"] == expected_owner


def test_proof_checker_scans_only_tex_reachable_from_main(tmp_path: Path) -> None:
    paper = tmp_path / "paper"
    sections = paper / "sections"
    template = paper / "venue_template"
    sections.mkdir(parents=True)
    template.mkdir()
    (paper / "main.tex").write_text(
        "\\documentclass{article}\n"
        "\\begin{document}\n"
        "\\input{sections/body}\n"
        "\\end{document}\n",
        encoding="utf-8",
    )
    body = sections / "body.tex"
    body.write_text("No formal result is declared here.\n", encoding="utf-8")
    (template / "sample.tex").write_text(
        "\\begin{theorem}Unused template theorem.\\end{theorem}\n",
        encoding="utf-8",
    )

    _, hashes, paths, theorem_count, errors = proof_source_bundle(tmp_path)

    assert errors == []
    assert hashes == {}
    assert paths == []
    assert theorem_count == 0

    body.write_text(
        "\\begin{theorem}Reachable theorem.\\end{theorem}\n"
        "\\begin{proof}Reachable proof.\\end{proof}\n",
        encoding="utf-8",
    )
    _, hashes, paths, theorem_count, errors = proof_source_bundle(tmp_path)

    assert errors == []
    assert set(hashes) == {"sections/body.tex"}
    assert paths == [body.resolve()]
    assert theorem_count == 2


def test_proof_checker_no_source_detection_is_stable_after_audit_output(
    tmp_path: Path,
) -> None:
    before = proof_source_bundle(tmp_path)
    assert before[1:] == ({}, [], 0, [])

    paper = tmp_path / "paper"
    paper.mkdir()
    (paper / "PROOF_AUDIT.json").write_text("{}", encoding="utf-8")
    after = proof_source_bundle(tmp_path)
    assert after == before

    sections = paper / "sections"
    sections.mkdir()
    (sections / "orphan.tex").write_text(
        "\\begin{theorem}Orphaned statement.\\end{theorem}\n",
        encoding="utf-8",
    )
    _, _, _, _, errors = proof_source_bundle(tmp_path)
    assert any("missing main TeX entrypoint" in item for item in errors)


def test_compile_risk_audit_rejects_stale_or_fake_pdf(tmp_path: Path) -> None:
    paper = tmp_path / "paper"
    paper.mkdir()
    tex = paper / "main.tex"
    pdf = paper / "main.pdf"
    tex.write_text(
        "\\documentclass{article}\\begin{document}x\\end{document}", encoding="utf-8"
    )
    pdf.write_bytes(b"not-a-pdf")
    _write_json(paper / "PAPER_BUILD.json", {"compile": {"success": True}})
    old = time.time() - 30
    os.utime(pdf, (old, old))

    report = node_risk_audit_service.audit_node(tmp_path, "compile", {})
    ids = {item["id"] for item in report["findings"]}

    assert "COMPILE-PDF-002" in ids
    assert "COMPILE-STALE-001" in ids
