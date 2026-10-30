"""Check manuscript inputs, completeness, and current table/source bindings.

Checks add findings to one PaperGateContext. Table acceptance is read-only:
missing or stale hashes must be repaired by the table producer."""

# ruff: noqa: F401
from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path
from typing import Any, Optional

from ..utils.atomic_write import atomic_write_json

from ..services.figure_artifacts import figure_artifact_registry
from ..services.manuscript_language import (
    find_internal_contract_references,
    find_visible_code_artifact_references,
)
from ..services.paper_drafting import (
    citation_keys as parsed_citation_keys,
    reference_keys,
    word_count,
)
from ..services.paper_profile import (
    FIGURE_ROLE_ALIASES,
    TABLE_ROLE_ALIASES,
    canonical_roles,
    paper_profile_service,
)
from ..services.simulation_policy import (
    FORBIDDEN_RENDERED_SIMULATION_LABELS,
    rendered_mode_framing_hits_outside_end_disclosure,
    simulation_disclosure_report,
    strip_latex_comments,
    visible_latex_prose,
    visible_watermark_commands,
)
from .paper_acceptance_context import PaperGateComplete, PaperGateContext
from .paper_acceptance_source import expand_tex_source, resolve_graphic_path


def initialize_paths(ctx: PaperGateContext) -> None:
    ctx.root = Path(ctx.project_path).resolve()


def initialize_paper_root(ctx: PaperGateContext) -> None:
    ctx.paper_root = ctx.root / "paper"


def initialize_main_path(ctx: PaperGateContext) -> None:
    ctx.main_path = ctx.paper_root / "main.tex"


def initialize_problems(ctx: PaperGateContext) -> None:
    ctx.problems: list[str] = []


def initialize_warnings(ctx: PaperGateContext) -> None:
    ctx.warnings: list[str] = []


def initialize_staged_report(ctx: PaperGateContext) -> None:
    ctx.staged_report: dict[str, Any] = {}


def initialize_staged_findings(ctx: PaperGateContext) -> None:
    ctx.staged_findings: list[dict[str, Any]] = []


def initialize_staged_targets(ctx: PaperGateContext) -> None:
    ctx.staged_target_files: list[str] = []


def validate_staged_draft(ctx: PaperGateContext) -> None:
    if ctx.require_staged:
        from ..services.paper_drafting import paper_drafting_service

        ctx.staged_report = paper_drafting_service.gate_report(
            ctx.project_path, ctx.paper_options
        )
        ctx.staged_findings = [
            item
            for item in ctx.staged_report.get("findings", [])
            if isinstance(item, dict)
        ]
        ctx.staged_target_files = ctx.host._revision_target_files(
            ctx.staged_findings, ctx.staged_report.get("target_files")
        )
        if ctx.staged_findings:
            ctx.problems.extend(
                (
                    "staged-paper: "
                    + str(item.get("plain_message") or item.get("message") or "")
                    for item in ctx.staged_findings
                    if str(
                        item.get("plain_message") or item.get("message") or ""
                    ).strip()
                )
            )
        else:
            ctx.problems.extend(
                (
                    "staged-paper: " + str(item)
                    for item in ctx.staged_report.get("issues", [])
                    if str(item).strip()
                )
            )


def require_main_document(ctx: PaperGateContext) -> None:
    if not ctx.main_path.exists() or ctx.main_path.stat().st_size == 0:
        missing_issue = f"Missing or empty {ctx.main_path}"
        if ctx.staged_findings:
            active_messages = [
                str(item.get("plain_message") or item.get("message") or "").strip()
                for item in ctx.staged_findings
                if str(item.get("plain_message") or item.get("message") or "").strip()
            ]
            raise PaperGateComplete(
                {
                    "accepted": False,
                    "reason": "staged paper section requires revision",
                    "summary": active_messages[0]
                    if active_messages
                    else "The active paper stage requires revision.",
                    "details": {
                        "paper": str(ctx.main_path),
                        "issues": active_messages,
                        "review_findings": ctx.staged_findings,
                        "target_files": ctx.staged_target_files,
                        "failed_stage": str(
                            ctx.staged_report.get("active_stage") or ""
                        ),
                        "semantic_no_progress": bool(
                            ctx.staged_report.get("semantic_no_progress")
                        ),
                        "assembly_pending": True,
                        "staged_drafting": ctx.staged_report,
                    },
                }
            )
        raise PaperGateComplete(
            {
                "accepted": False,
                "reason": "paper main.tex missing",
                "summary": missing_issue,
                "details": {
                    "paper": str(ctx.main_path),
                    "issues": [*ctx.problems, missing_issue],
                    "review_findings": [],
                    "target_files": [],
                    "staged_drafting": ctx.staged_report,
                },
            }
        )


def locate_asset_plan(ctx: PaperGateContext) -> None:
    ctx.asset_plan_path = ctx.root / "figures" / "SCIENTIFIC_ASSET_PLAN.json"


def initialize_asset_plan(ctx: PaperGateContext) -> None:
    ctx.asset_plan: dict = {}


def load_asset_plan(ctx: PaperGateContext) -> None:
    if not ctx.asset_plan_path.is_file() or ctx.asset_plan_path.stat().st_size == 0:
        ctx.problems.append("missing figures/SCIENTIFIC_ASSET_PLAN.json")
    else:
        try:
            loaded_plan = json.loads(ctx.asset_plan_path.read_text(encoding="utf-8"))
            ctx.asset_plan = loaded_plan if isinstance(loaded_plan, dict) else {}
        except (OSError, json.JSONDecodeError):
            ctx.problems.append("scientific asset plan is not valid JSON")


def read_evidence_mode(ctx: PaperGateContext) -> None:
    ctx.evidence_mode = str(ctx.asset_plan.get("evidence_mode") or "")


def read_submission_eligibility(ctx: PaperGateContext) -> None:
    ctx.submission_eligible = bool(ctx.asset_plan.get("submission_eligible"))


def load_manuscript_profile(ctx: PaperGateContext) -> None:
    ctx.manuscript_profile = paper_profile_service.load(ctx.root)


def require_manuscript_profile(ctx: PaperGateContext) -> None:
    if not ctx.manuscript_profile:
        from ..services.publication_style import publication_style_service

        publication_style = publication_style_service.prepare(
            ctx.root,
            str((ctx.paper_options or {}).get("research_direction") or ""),
            target_venue=str((ctx.paper_options or {}).get("target_venue") or ""),
            research_family=str((ctx.paper_options or {}).get("research_family") or ""),
            study_archetype=str((ctx.paper_options or {}).get("study_archetype") or ""),
        )
        ctx.manuscript_profile = paper_profile_service.build(
            target_venue=str((ctx.paper_options or {}).get("target_venue") or ""),
            evidence_mode=ctx.evidence_mode,
            submission_eligible=ctx.submission_eligible,
            research_family=str(
                publication_style.get("family") or "generic_quantitative"
            ),
            study_archetype=str(
                publication_style.get("study_archetype") or "generic_empirical"
            ),
        )


def validate_complete_evidence_mode(ctx: PaperGateContext) -> None:
    if ctx.evidence_mode in {"executed", "existing_results", "secondary_analysis"}:
        if not ctx.submission_eligible:
            ctx.problems.append(
                f"{ctx.evidence_mode} mode is not backed by a submission-eligible evidence plan"
            )
    elif ctx.submission_eligible:
        ctx.problems.append(
            f"non-empirical evidence mode {ctx.evidence_mode or 'unspecified'} cannot be submission-eligible"
        )


def validate_experiment_request(ctx: PaperGateContext) -> None:
    if ctx.asset_plan.get("experiment_requested") or ctx.evidence_mode in {
        "existing_results",
        "secondary_analysis",
    }:
        ctx.problems.extend(
            (
                str(item)
                for item in ctx.asset_plan.get("missing_requirements", [])
                if str(item).strip()
            )
        )


def locate_table_manifest(ctx: PaperGateContext) -> None:
    ctx.table_manifest_path = ctx.paper_root / "tables" / "TABLE_MANIFEST.json"


def initialize_table_artifacts(ctx: PaperGateContext) -> None:
    ctx.table_artifacts: list[Path] = []


def initialize_table_entries(ctx: PaperGateContext) -> None:
    ctx.table_entries: list[dict] = []


def table_manifest_missing(ctx: PaperGateContext) -> None:
    if not ctx.table_manifest_path.exists():
        ctx.problems.append("missing paper/tables/TABLE_MANIFEST.json")


def table_manifest_load_1(ctx: PaperGateContext) -> None:
    if not not ctx.table_manifest_path.exists():
        try:
            ctx.table_manifest = json.loads(
                ctx.table_manifest_path.read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError):
            ctx.table_manifest = {"tables": []}
            ctx.problems.append("table manifest is not valid JSON")
        if isinstance(ctx.table_manifest, dict):
            from ..services.paper_artifacts import bind_table_manifest_hashes

            ctx.table_manifest, table_hash_issues, _ = (
                bind_table_manifest_hashes(
                    ctx.root, ctx.table_manifest
                )
            )
            ctx.problems.extend(table_hash_issues)


def table_manifest_load_2(ctx: PaperGateContext) -> None:
    if not not ctx.table_manifest_path.exists():
        ctx.table_entries = [
            item
            for item in ctx.table_manifest.get("tables", [])
            if isinstance(item, dict)
        ]
        minimum = int(ctx.manuscript_profile.get("table_contract", {}).get("minimum_tables", 2))
        if len(ctx.table_entries) < minimum:
            ctx.problems.append(
                f"need at least {minimum} persisted table artifacts, found {len(ctx.table_entries)}"
            )


def table_manifest_load_3(ctx: PaperGateContext) -> None:
    if not not ctx.table_manifest_path.exists():
        for item in ctx.table_entries:
            for key in ("latex_path", "data_path"):
                value = item.get(key)
                candidate = (ctx.root / value).resolve() if value else None
                if (
                    not candidate
                    or not candidate.exists()
                    or candidate.stat().st_size == 0
                ):
                    ctx.problems.append(f"missing table artifact: {value or key}")
                else:
                    ctx.table_artifacts.append(candidate)
        ctx.scientific_table_roles = {
            "result",
            "ablation",
            "robustness",
            "study_design",
            "method_components",
            "dataset",
            "baseline",
            "efficiency",
            "calibration",
            "error_analysis",
        }


def table_manifest_load_4(ctx: PaperGateContext) -> None:
    if not not ctx.table_manifest_path.exists():
        for item in ctx.table_entries:
            role = str(item.get("scientific_role") or "")
            if role not in ctx.scientific_table_roles:
                continue
            if not item.get("source_data"):
                ctx.problems.append(
                    f"scientific table {item.get('id')} has no source_data"
                )
            else:
                for raw_source in item.get("source_data", []):
                    source = Path(str(raw_source))
                    candidate = source if source.is_absolute() else ctx.root / source
                    try:
                        candidate = candidate.resolve()
                        candidate.relative_to(ctx.root)
                    except (OSError, ValueError):
                        ctx.problems.append(
                            f"scientific table {item.get('id')} source escapes project: {raw_source}"
                        )
                        continue
                    if not candidate.is_file() or candidate.stat().st_size == 0:
                        ctx.problems.append(
                            f"scientific table {item.get('id')} source is missing: {raw_source}"
                        )
            if (
                role in {"result", "ablation", "robustness"}
                and item.get("evidence_status") == "executed"
                and (not str(item.get("uncertainty_encoding") or "").strip())
            ):
                ctx.problems.append(
                    f"executed table {item.get('id')} has no uncertainty encoding"
                )
        ctx.table_ids = {str(item.get("id") or "") for item in ctx.table_entries}


def table_manifest_load_5(ctx: PaperGateContext) -> None:
    # Table roles are evidence- and contribution-driven. No universal pair of
    # design tables is required across empirical, theoretical, clinical,
    # systems, or qualitative manuscripts.
    return None


def table_manifest_load_6(ctx: PaperGateContext) -> None:
    if not not ctx.table_manifest_path.exists():
        if ctx.evidence_mode in {"executed", "existing_results"}:
            executed_result_tables = [
                item
                for item in ctx.table_entries
                if item.get("scientific_role") == "result"
                and item.get("evidence_status") == "executed"
            ]
            if not executed_result_tables:
                ctx.problems.append(
                    f"{ctx.evidence_mode} paper requires an evidence-backed main result table"
                )
        ctx.table_role_values = [
            str(item.get("scientific_role") or "") for item in ctx.table_entries
        ] + [str(item.get("id") or "") for item in ctx.table_entries]


def table_manifest_load_7(ctx: PaperGateContext) -> None:
    if not not ctx.table_manifest_path.exists():
        ctx.canonical_table_roles = canonical_roles(
            ctx.table_role_values, TABLE_ROLE_ALIASES
        )
        ctx.required_table_roles = set(
            ctx.manuscript_profile.get("table_contract", {}).get("required_roles", [])
        )


def table_manifest_load_8(ctx: PaperGateContext) -> None:
    if not not ctx.table_manifest_path.exists():
        missing_table_roles = sorted(
            ctx.required_table_roles - ctx.canonical_table_roles
        )
        if missing_table_roles:
            ctx.problems.append(
                "paper is missing core scientific table roles: "
                + ", ".join(missing_table_roles)
            )


def validate_empirical_table_manifest(ctx: PaperGateContext) -> None:
    if not not ctx.table_manifest_path.exists():
        if ctx.manuscript_profile.get("publication_track") in {"empirical_submission", "simulation_draft"}:
            for role in ("main_results", "ablation", "robustness_or_calibration"):
                matching = [
                    item
                    for item in ctx.table_entries
                    if role
                    in canonical_roles(
                        [
                            str(item.get("scientific_role") or ""),
                            str(item.get("id") or ""),
                        ],
                        TABLE_ROLE_ALIASES,
                    )
                ]
                if matching and (
                    not any(
                        (
                            item.get("evidence_status") == "executed"
                            and str(item.get("provenance_kind") or "").strip()
                            or (
                                ctx.evidence_mode == "synthetic_preview"
                                and item.get("evidence_status") == "synthetic_preview"
                                and (
                                    item.get("provenance_kind")
                                    == "deterministic_simulation_preview"
                                )
                            )
                            for item in matching
                        )
                    )
                ):
                    ctx.problems.append(
                        f"core empirical table role {role} lacks executed provenance"
                    )
        elif (
            ctx.manuscript_profile.get("publication_track")
            == "empirical_structure_preview"
        ):
            for role in ("main_results", "ablation", "robustness_or_calibration"):
                matching = [
                    item
                    for item in ctx.table_entries
                    if role
                    in canonical_roles(
                        [
                            str(item.get("scientific_role") or ""),
                            str(item.get("id") or ""),
                        ],
                        TABLE_ROLE_ALIASES,
                    )
                ]
                if matching and (
                    not all(
                        (
                            item.get("evidence_status") == "synthetic_preview"
                            for item in matching
                            if str(item.get("scientific_role") or "")
                            in {"result", "ablation", "robustness", "calibration"}
                        )
                    )
                ):
                    ctx.problems.append(
                        f"preview table role {role} is not isolated as synthetic_preview"
                    )


def validate_simulation_table_manifest(ctx: PaperGateContext) -> None:
    if not not ctx.table_manifest_path.exists():
        if ctx.evidence_mode == "synthetic_preview":
            simulation_manifest_path = (
                ctx.root
                / "experiments"
                / "results"
                / "simulated"
                / "SIMULATION_MANIFEST.json"
            ).resolve()
            try:
                simulation_manifest = json.loads(
                    simulation_manifest_path.read_text(encoding="utf-8-sig")
                )
            except (OSError, UnicodeError, json.JSONDecodeError):
                simulation_manifest = None
            if not isinstance(simulation_manifest, dict):
                ctx.problems.append(
                    "synthetic_preview requires canonical experiments/results/simulated/SIMULATION_MANIFEST.json"
                )
            else:
                raw_table = str(simulation_manifest.get("paper_table") or "").replace(
                    "\\", "/"
                )
                if raw_table != "paper/tables/synthetic_preview_results.tex":
                    ctx.problems.append(
                        "synthetic simulation manifest is not bound to canonical preview table"
                    )
                else:
                    preview_table = (ctx.root / raw_table).resolve()
                    try:
                        preview_table.relative_to(ctx.root)
                    except ValueError:
                        preview_table = None
                    if (
                        preview_table is None
                        or not preview_table.is_file()
                        or preview_table.stat().st_size == 0
                    ):
                        ctx.problems.append(
                            "canonical synthetic preview table is missing"
                        )
                    else:
                        from ..services.simulation_table_projection_binding import verify_simulation_table_projection
                        try:
                            verify_simulation_table_projection(Path(ctx.project_path), simulation_manifest)
                        except (OSError, UnicodeError, ValueError, KeyError, TypeError) as error:
                            ctx.problems.append(
                                "synthetic simulation table has no verified original or paper-owned projection binding: "
                                + str(error)
                            )


def require_table_entries(ctx: PaperGateContext) -> None:
    if not ctx.table_entries:
        ctx.canonical_table_roles: set[str] = set()


def initialize_source_map(ctx: PaperGateContext) -> None:
    ctx.source_text: dict[Path, str] = {}


def initialize_source_queue(ctx: PaperGateContext) -> None:
    ctx.queue = [ctx.main_path]


def collect_reachable_sources(ctx: PaperGateContext) -> None:
    while ctx.queue:
        source = ctx.queue.pop(0).resolve()
        if source in ctx.source_text or not source.exists() or (not source.is_file()):
            continue
        try:
            source.relative_to(ctx.root)
        except ValueError:
            continue
        content = source.read_text(encoding="utf-8", errors="replace")
        ctx.source_text[source] = content
        for raw_ref in re.findall("\\\\(?:input|include)\\{([^}]+)\\}", content):
            ref = raw_ref.strip()
            if not ref:
                continue
            candidates = [ctx.paper_root / ref, source.parent / ref]
            for candidate in candidates:
                if candidate.suffix.lower() != ".tex":
                    candidate = candidate.with_suffix(".tex")
                if candidate.exists():
                    ctx.queue.append(candidate)
                    break


def read_main_source(ctx: PaperGateContext) -> None:
    ctx.main_text = ctx.source_text.get(ctx.main_path.resolve(), "")


def combine_sources(ctx: PaperGateContext) -> None:
    ctx.combined = "\n".join(ctx.source_text.values())


def expand_main_source(ctx: PaperGateContext) -> None:
    ctx.expanded_main = (
        expand_tex_source(ctx.main_path, ctx.source_text, ctx.paper_root, set())
        or ctx.main_text
    )


def compile_admin_language_rule(ctx: PaperGateContext) -> None:
    ctx.administrative_language = re.compile(
        "(?:publication[_\\\\ ]ready|Claim-Linked Scientific Assets|claim[- ]to[- ]evidence contract and current support status|artifact[- ]first research protocol|evidence status|planned result templates?|workflow (?:status|artifact)|DEMO VALUES)",
        flags=re.IGNORECASE,
    )


def initialize_admin_hits(ctx: PaperGateContext) -> None:
    ctx.administrative_hits: list[str] = []


def find_admin_language(ctx: PaperGateContext) -> None:
    for source, content in ctx.source_text.items():
        matches = list(ctx.administrative_language.finditer(content))
        matches.extend(re.finditer("\\bNOT EVIDENCE\\b", content))
        for match in matches:
            line = content.count("\n", 0, match.start()) + 1
            try:
                display_source = source.relative_to(ctx.root)
            except ValueError:
                display_source = source
            ctx.administrative_hits.append(
                f"{display_source}:{line} ({match.group(0)})"
            )


def reject_admin_language(ctx: PaperGateContext) -> None:
    if ctx.administrative_hits:
        ctx.problems.append(
            "manuscript exposes internal workflow, readiness, or evidence-administration prose at "
            + ", ".join(ctx.administrative_hits[:6])
        )


def collect_contract_ids(ctx: PaperGateContext) -> None:
    ctx.contract_ids = {
        str(item.get("id") or "").strip()
        for group in (
            ctx.asset_plan.get("claims", []),
            ctx.asset_plan.get("mechanisms", []),
        )
        for item in group
        if isinstance(item, dict) and str(item.get("id") or "").strip()
    }
