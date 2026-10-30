"""Persistent, domain-neutral contracts for every research workflow stage.

The contract keeps node prompts anchored to the same accepted idea and evidence
state.  It also records latent risks for all stages so a green upstream gate
does not hide downstream scientific drift.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

from ..utils.atomic_write import atomic_write_json


NODE_CONTRACTS: dict[str, dict[str, Any]] = {
    "lit": {
        "purpose": "Build a traceable evidence map, not a list of paper summaries.",
        "inputs": ["literature/RESEARCH_BRIEF.md", ".merak/research_strategy.json"],
        "outputs": ["literature/survey.md", "literature/references.bib"],
        "checks": [
            "search window and sources match the user strategy",
            "core metadata is traceable",
            "conflicting evidence and testable gaps are synthesized",
        ],
        "risks": ["citation hallucination", "search-selection bias", "recency bias"],
    },
    "idea": {
        "purpose": "Turn evidence gaps into falsifiable candidate hypotheses.",
        "inputs": ["literature/survey.md", "literature/references.bib"],
        "outputs": ["ideas/ideas.md"],
        "checks": [
            "each candidate names a mechanism and an observable consequence",
            "nearest work and alternative explanations are explicit",
            "feasibility is separated from novelty",
        ],
        "risks": ["feature-wishlist ideas", "unsupported novelty", "infeasible evidence plan"],
    },
    "novelty": {
        "purpose": "Select and freeze one defensible claim-level novelty delta.",
        "inputs": ["ideas/ideas.md", "literature/survey.md", "literature/references.bib"],
        "outputs": ["ideas/novelty_report.md", "ideas/SELECTED_IDEA.json"],
        "checks": [
            "nearest-neighbor claims are retrieved rather than recalled",
            "uncertainty is preserved as UNKNOWN",
            "claims, mechanisms, and falsification conditions use stable IDs",
        ],
        "risks": ["duplicate contribution", "title-only comparison", "selection drift"],
    },
    "exp-design": {
        "purpose": "Implement the frozen mechanisms and map every claim to decisive evidence.",
        "inputs": ["ideas/SELECTED_IDEA.json", "ideas/novelty_report.md"],
        "outputs": [
            "experiments/EXPERIMENT_PLAN.md",
            "experiments/METHOD_CONTRACT.json",
            "experiments/RUN_SPEC.json",
            "experiments/configs/main.yaml",
            "experiments/src",
        ],
        "checks": [
            "required mechanisms map to real code and config",
            "splits, leakage controls, baselines, ablations, and statistics are executable",
            "failure and pivot criteria are prespecified",
        ],
        "risks": ["convenient substitute method", "data leakage", "unfair baseline", "non-runnable scaffold"],
    },
    "exp-run": {
        "purpose": "Produce immutable, provenance-backed runs or an explicit not-run state.",
        "inputs": [
            "experiments/METHOD_CONTRACT.json",
            "experiments/RUN_SPEC.json",
            "experiments/configs",
            "experiments/src",
        ],
        "outputs": ["experiments/logs", "experiments/results"],
        "checks": [
            "preflight and health checks precede expensive runs",
            "runtime events own result hashes",
            "anomalies stop or quarantine invalid runs",
        ],
        "risks": ["silent crash", "stale remote code", "invalid retry reuse", "unowned metrics"],
    },
    "results": {
        "purpose": "Convert owned measurements into bounded claim decisions.",
        "inputs": [
            "ideas/SELECTED_IDEA.json",
            "experiments/METHOD_CONTRACT.json",
            "experiments/results",
            "experiments/logs",
        ],
        "outputs": ["experiments/results/analysis.md"],
        "checks": [
            "executed and planned artifacts are separated",
            "uncertainty matches the independent unit",
            "supported, contradicted, and pending claims are explicit",
        ],
        "risks": ["template values promoted to evidence", "invalid significance test", "cherry-picking"],
    },
    "figure": {
        "purpose": "Create only claim-bearing, source-traceable scientific assets.",
        "inputs": [
            "ideas/SELECTED_IDEA.json",
            "experiments/METHOD_CONTRACT.json",
            "experiments/EXPERIMENT_PLAN.md",
            "experiments/results/analysis.md",
        ],
        "outputs": [
            "figures/SCIENTIFIC_ASSET_PLAN.json",
            "figures/FIGURE_SPECS.json",
            "figures/FIGURE_MANIFEST.json",
        ],
        "checks": [
            "every asset answers a declared scientific question",
            "editable source and rendered preview agree",
            "quantitative plots use provenance-backed data and uncertainty",
        ],
        "risks": ["generic workflow art", "duplicate figures", "source-preview drift", "fabricated values"],
    },
    "narrative": {
        "purpose": "Build a claim-evidence narrative without changing the accepted idea.",
        "inputs": [
            "ideas/SELECTED_IDEA.json",
            "experiments/METHOD_CONTRACT.json",
            "experiments/results/analysis.md",
        ],
        "outputs": ["NARRATIVE_REPORT.md"],
        "checks": [
            "motivation, mechanism, tests, findings, and limitations form one argument",
            "claim maturity is explicit",
            "negative and pending evidence is retained",
        ],
        "risks": ["idea drift", "overclaiming", "omitted negative evidence"],
    },
    "paper": {
        "purpose": "Report the research record, not manufacture a complete-looking result.",
        "inputs": [
            "literature",
            "ideas/SELECTED_IDEA.json",
            "experiments/METHOD_CONTRACT.json",
            "experiments/results/analysis.md",
            "figures/FIGURE_MANIFEST.json",
            "NARRATIVE_REPORT.md",
        ],
        "outputs": ["paper/main.tex"],
        "checks": [
            "title, method, claims, tables, and figures trace to contracts",
            "evidence status controls wording",
            "limitations and falsification results are visible",
        ],
        "risks": ["unsupported empirical language", "citation drift", "decorative figures", "filler"],
    },
    "review": {
        "purpose": "Resolve substantive scientific objections and record what changed.",
        "inputs": [
            "paper/main.tex",
            "ideas/SELECTED_IDEA.json",
            "experiments/results/analysis.md",
            "figures/SCIENTIFIC_ASSET_PLAN.json",
        ],
        "outputs": [
            "review-stage/REVIEW_STATE.json",
            "review-stage/pdf-layout/",
            "review-stage/pdf-previews/",
            "paper/main.tex",
            "paper/main_round0_original.pdf",
            "paper/main_roundN.pdf",
        ],
        "checks": [
            "critical findings map to concrete revisions or explicit unresolved risks",
            "the reviewer cannot self-certify by printing a score alone",
            "every round is recompiled and hash-bound to a preserved PDF snapshot",
            "the reviewer inspects PDF figures, tables, captions, and page layout",
            "claim and evidence boundaries remain intact",
        ],
        "risks": [
            "self-reported score gaming",
            "TeX-only review that misses rendered layout defects",
            "stale or overwritten review PDFs",
            "cosmetic-only revision",
            "review-induced claim drift",
        ],
    },
    "audit": {
        "purpose": "Independently trace experiment, result, paper, citation, and kill arguments.",
        "inputs": ["paper", "experiments", "literature/references.bib", ".merak/execution_events.jsonl"],
        "outputs": [
            "audit-results/AUDIT_RESULTS.json",
            "audit-results/AUDIT_BUILD.json",
            "paper/PROOF_AUDIT.json",
        ],
        "checks": [
            "each verdict includes inspected evidence",
            "encoding and tool failures cannot become PASS",
            "blocking counterevidence propagates downstream",
        ],
        "risks": ["shallow file-existence audit", "encoding failure", "missing counterevidence"],
    },
    "compile": {
        "purpose": "Produce a reproducible PDF only after scientific audit acceptance.",
        "inputs": [
            "paper/main.tex",
            "audit-results/AUDIT_RESULTS.json",
            "paper/PROOF_AUDIT.json",
        ],
        "outputs": ["paper/main.pdf", "paper/PAPER_BUILD.json"],
        "checks": [
            "LaTeX errors and unresolved references are repaired",
            "the measured page count is reported as a soft target",
            "the compiled PDF corresponds to current sources",
        ],
        "risks": ["stale PDF", "hidden compile warnings", "layout changes that distort science"],
    },
    "ppt": {
        "purpose": "Create an evidence-faithful research talk from the accepted paper and assets.",
        "inputs": ["paper/main.tex", "paper/main.pdf", "figures/FIGURE_MANIFEST.json"],
        "outputs": ["slides/main.tex", "slides/main.pdf", "slides/SLIDE_BUILD.json"],
        "checks": [
            "slides preserve claim maturity and citations",
            "figures are selected for the argument rather than decoration",
            "the deck compiles and remains legible",
        ],
        "risks": ["stronger claims than the paper", "generic deck", "unreadable figures"],
    },
}


def _evidence_mode(options: dict[str, Any]) -> str:
    if options.get("run_experiment") is True:
        return "executed"
    requested = str(
        options.get("non_experiment_evidence_mode") or "design_only"
    ).strip().casefold()
    return requested if requested in {
        "synthetic_preview", "existing_results", "secondary_analysis", "design_only",
    } else "design_only"


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file() or path.stat().st_size == 0:
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig", errors="replace"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _has_content(path: Path) -> bool:
    if path.is_file():
        return path.stat().st_size > 0
    if path.is_dir():
        return any(item.is_file() and item.stat().st_size > 0 for item in path.rglob("*"))
    return False


class ResearchWorkflowContractService:
    relative_path = Path(".merak/RESEARCH_WORKFLOW_CONTRACT.json")

    @staticmethod
    def _selected_context(root: Path) -> dict[str, Any]:
        selected = _read_json(root / "ideas" / "SELECTED_IDEA.json")
        method = _read_json(root / "experiments" / "METHOD_CONTRACT.json")
        assets = _read_json(root / "figures" / "SCIENTIFIC_ASSET_PLAN.json")
        selected_path = root / "ideas" / "SELECTED_IDEA.json"
        selected_hash = ""
        if selected_path.is_file():
            selected_hash = hashlib.sha256(selected_path.read_bytes()).hexdigest()
        return {
            "selected": selected,
            "method": method,
            "assets": assets,
            "selected_hash": selected_hash,
        }

    def audit(
        self,
        project_path: str | Path,
        direction: str,
        options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        root = Path(project_path).expanduser().resolve()
        options = dict(options or {})
        context = self._selected_context(root)
        selected = context["selected"]
        selected_title = str(selected.get("title") or "").strip()
        nodes: dict[str, Any] = {}
        for node_id, contract in NODE_CONTRACTS.items():
            inputs = {
                relative: _has_content(root / relative)
                for relative in contract["inputs"]
            }
            outputs = {
                relative: _has_content(root / relative)
                for relative in contract["outputs"]
            }
            nodes[node_id] = {
                **contract,
                "inputs_present": inputs,
                "outputs_present": outputs,
                "ready_inputs": all(inputs.values()) if inputs else True,
                "output_complete": all(outputs.values()) if outputs else True,
            }

        cross_node_issues: list[str] = []
        method_title = str(context["method"].get("selected_idea") or "").strip()
        asset_title = str(context["assets"].get("selected_idea") or "").strip()
        if selected_title and method_title and selected_title != method_title:
            cross_node_issues.append("METHOD_CONTRACT selected_idea differs from SELECTED_IDEA title.")
        if selected_title and asset_title and selected_title != asset_title:
            cross_node_issues.append("SCIENTIFIC_ASSET_PLAN selected_idea is truncated or differs from SELECTED_IDEA title.")
        expected_hash = str(context["method"].get("idea_contract_sha256") or "").strip()
        if expected_hash and context["selected_hash"] and expected_hash != context["selected_hash"]:
            cross_node_issues.append("METHOD_CONTRACT is pinned to a stale SELECTED_IDEA hash.")
        if options.get("run_experiment") is not True and str(options.get("gpu_target") or "none") not in {"", "none"}:
            cross_node_issues.append("GPU target is configured even though experiment execution is disabled.")

        return {
            "schema": 1,
            "generated_at": time.time(),
            "direction": str(direction or "").strip(),
            "experiment_requested": options.get("run_experiment") is True,
            "selected_idea": selected_title,
            "selected_idea_sha256": context["selected_hash"],
            "hypothesis": str(selected.get("hypothesis") or "").strip(),
            "claim_ids": [
                str(item.get("id") or "")
                for item in selected.get("claims") or []
                if isinstance(item, dict)
            ],
            "mechanism_ids": [
                str(item.get("id") or "")
                for item in selected.get("mechanisms") or []
                if isinstance(item, dict) and item.get("required", True)
            ],
            "cross_node_issues": cross_node_issues,
            "nodes": nodes,
        }

    def prepare(
        self,
        project_path: str | Path,
        direction: str,
        options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        root = Path(project_path).expanduser().resolve()
        payload = self.audit(root, direction, options)
        path = root / self.relative_path
        atomic_write_json(path, payload)
        return payload

    def prompt(
        self,
        project_path: str | Path,
        node_id: str,
        direction: str,
        options: dict[str, Any] | None = None,
    ) -> str:
        root = Path(project_path).expanduser().resolve()
        context = self._selected_context(root)
        selected = context["selected"]
        contract = NODE_CONTRACTS.get(node_id, {})
        claims = [
            f"{item.get('id')}: {str(item.get('statement') or '').strip()}"
            for item in selected.get("claims") or []
            if isinstance(item, dict)
        ]
        mechanisms = [
            f"{item.get('id')}: {str(item.get('name') or '').strip()} - "
            f"{str(item.get('description') or '').strip()}"
            for item in selected.get("mechanisms") or []
            if isinstance(item, dict) and item.get("required", True)
        ]
        falsification = [
            str(item).strip()
            for item in selected.get("falsification_conditions") or []
            if str(item).strip()
        ]
        evidence_mode = _evidence_mode(options or {})
        return """## Frozen Research Workflow Contract
Stage: {node_id}
Stage purpose: {purpose}
Research direction: {direction}
Accepted idea: {title}
Hypothesis: {hypothesis}
Evidence mode: {evidence_mode}

Required claims:
{claims}

Required mechanisms:
{mechanisms}

Falsification boundaries:
{falsification}

Authoritative inputs: {inputs}
Canonical outputs: {outputs}
Stage checks: {checks}
Known latent risks: {risks}

Do not redefine the accepted idea, silently strengthen a pending claim, or replace a
required mechanism with an easier implementation. If an authoritative input is absent,
record one explicit evidence gap and take only actions valid for the current evidence mode.
""".format(
            node_id=node_id,
            purpose=contract.get("purpose", "Produce the canonical stage artifact."),
            direction=str(direction or "").strip() or "(not declared)",
            title=str(selected.get("title") or "").strip() or "(not selected yet)",
            hypothesis=str(selected.get("hypothesis") or "").strip() or "(not frozen yet)",
            evidence_mode=evidence_mode,
            claims="\n".join(f"- {item}" for item in claims) or "- Not frozen at this stage.",
            mechanisms="\n".join(f"- {item}" for item in mechanisms) or "- Not frozen at this stage.",
            falsification="\n".join(f"- {item}" for item in falsification) or "- Not frozen at this stage.",
            inputs=", ".join(contract.get("inputs", [])),
            outputs=", ".join(contract.get("outputs", [])),
            checks="; ".join(contract.get("checks", [])),
            risks="; ".join(contract.get("risks", [])),
        )


from ..contracts.workflow_nodes import WORKFLOW_NODES

# This catalogue owns content, never execution order.
NODE_CONTRACTS = {node["id"]: NODE_CONTRACTS[node["id"]] for node in WORKFLOW_NODES}
research_workflow_contract_service = ResearchWorkflowContractService()
