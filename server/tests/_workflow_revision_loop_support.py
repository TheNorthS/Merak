from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path

import pytest

from server.agent.engine import AgentEngine, agent_engine
from server.services.paper_compiler import CompileError, CompileResult
from server.workflows.engine import NodeStatus, WorkflowEngine, WorkflowNode, WorkflowRun
from server.workflows.run_state import RunState


def _start_run_state(tmp_path: Path, run_id: str, nodes: list[WorkflowNode]) -> RunState:
    state = RunState(str(tmp_path), run_id)
    state.start(
        [{"id": node.id, "name": node.name, "skill": node.skill} for node in nodes],
        {
            "direction": "test direction",
            "effort": "balanced",
            "assurance": "draft",
            "options": {"research_quality_mode": "rigorous"},
        },
    )
    return state


def _rejected(summary: str = "missing evidence") -> dict:
    return {
        "accepted": False,
        "reason": "research depth contract failed",
        "summary": summary,
        "details": {
            "research_quality": {
                "score": 0.4,
                "threshold": 0.58,
                "issues": [summary],
                "report_path": "quality.json",
            }
        },
    }


def _accepted() -> dict:
    return {
        "accepted": True,
        "verdict_id": "test:accepted",
        "reviewer": "deterministic:test",
        "summary": "accepted",
        "details": {},
    }


def _write_review_layout_routing_fixture(
    root: Path,
    *,
    kind: str,
) -> dict:
    paper = root / "paper"
    sections = paper / "sections"
    tables = paper / "tables"
    figures = root / "figures"
    layout_dir = root / "review-stage" / "pdf-layout"
    for directory in (sections, tables, figures, layout_dir):
        directory.mkdir(parents=True, exist_ok=True)
    paper.joinpath("main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\n"
        "\\input{sections/03_method}\n\\input{tables/results}\n"
        "\\end{document}\n",
        encoding="utf-8",
    )
    if kind == "figure":
        page_number = 5
        label = "fig:method-architecture"
        issue = "very small text detected (3.8 pt)"
        sections.joinpath("03_method.tex").write_text(
            "\\begin{figure}\n"
            "\\includegraphics{../figures/method_architecture.pdf}\n"
            "\\caption{Method architecture and information flow.}\n"
            f"\\label{{{label}}}\n"
            "\\end{figure}\n",
            encoding="utf-8",
        )
        tables.joinpath("results.tex").write_text("Results.\n", encoding="utf-8")
        figures.joinpath("method_architecture.pdf").write_bytes(b"figure-output")
        figures.joinpath("method_architecture.figurespec.json").write_text(
            '{"schema": 1}\n',
            encoding="utf-8",
        )
        figures.joinpath("FIGURE_MANIFEST.json").write_text(
            json.dumps({
                "schema": 1,
                "figures": [{
                    "id": "method_architecture",
                    "output_path": "figures/method_architecture.pdf",
                    "source_path": "figures/method_architecture.figurespec.json",
                    "caption": "Method architecture and information flow.",
                }],
            }),
            encoding="utf-8",
        )
    else:
        page_number = 8
        label = "tab:main-results"
        issue = "5 possible overlapping text-block pair(s)"
        sections.joinpath("03_method.tex").write_text("Method.\n", encoding="utf-8")
        tables.joinpath("results.tex").write_text(
            "\\begin{table}\n"
            "\\caption{Main comparison with uncertainty intervals.}\n"
            f"\\label{{{label}}}\n"
            "\\begin{tabular}{ll} A & B \\\\ \\end{tabular}\n"
            "\\end{table}\n",
            encoding="utf-8",
        )
        figures.joinpath("FIGURE_MANIFEST.json").write_text(
            '{"schema": 1, "figures": []}\n',
            encoding="utf-8",
        )
        tables.joinpath("TABLE_MANIFEST.json").write_text(
            json.dumps({
                "schema": 3,
                "tables": [{
                    "id": "main_results",
                    "label": label,
                    "latex_path": "paper/tables/results.tex",
                    "data_path": "paper/tables/results.csv",
                }],
            }),
            encoding="utf-8",
        )
    paper.joinpath("main.aux").write_text(
        f"\\newlabel{{{label}}}{{{{1}}{{{page_number}}}{{Caption}}{{float.1}}{{}}}}\n",
        encoding="utf-8",
    )
    pdf_hash = "a" * 64
    report_path = layout_dir / "main_round0_original.json"
    report_path.write_text(
        json.dumps({
            "schema": 1,
            "pdf_sha256": pdf_hash,
            "page_count": page_number,
            "pages": [{
                "page": page_number,
                "minimum_font_pt": 3.8 if kind == "figure" else 7.0,
                "possible_layout_findings": [issue],
            }],
        }),
        encoding="utf-8",
    )
    from server.workflows.review_audit import review_source_bundle

    source_hash, _ = review_source_bundle(root)
    snapshot_path = "paper/main_round0_original.pdf"
    return {
        "managed_by": "cross_model_review_loop",
        "source_bundle_sha256": source_hash,
        "rounds": [{
            "round": 1,
            "pdf_snapshot": snapshot_path,
            "visual_review": {
                "_source_bundle_sha256": source_hash,
            },
        }],
        "pdf_snapshots": [{
            "round": 0,
            "compiled_at": 1.0,
            "pdf_sha256": pdf_hash,
            "source_bundle_sha256": source_hash,
            "snapshot_path": snapshot_path,
            "layout_report_path": (
                "review-stage/pdf-layout/main_round0_original.json"
            ),
        }],
    }


def _rebind_review_layout_state(root: Path, state: dict) -> None:
    from server.workflows.review_audit import review_source_bundle

    source_hash, _ = review_source_bundle(root)
    state["source_bundle_sha256"] = source_hash
    state["rounds"][-1]["visual_review"][
        "_source_bundle_sha256"
    ] = source_hash
    state["pdf_snapshots"][-1]["source_bundle_sha256"] = source_hash
