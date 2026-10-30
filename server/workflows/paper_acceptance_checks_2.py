"""Check manuscript framing, structure, claims, and evidence presentation.

These checks share the coordinator's PaperGateContext; they do not represent
alternate versions of the paper gate or replace scientific source artifacts."""

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


def find_exposed_contract_ids(ctx: PaperGateContext) -> None:
    ctx.exposed_ids = find_internal_contract_references(ctx.combined, ctx.contract_ids)


def reject_exposed_contract_ids(ctx: PaperGateContext) -> None:
    if ctx.exposed_ids:
        ctx.problems.append(
            "manuscript exposes internal contract IDs: " + ", ".join(ctx.exposed_ids)
        )


def strip_comments(ctx: PaperGateContext) -> None:
    ctx.visible_manuscript = strip_latex_comments(ctx.expanded_main)


def normalize_visible_prose(ctx: PaperGateContext) -> None:
    ctx.normalized_manuscript = " ".join(ctx.visible_manuscript.split()).casefold()


def find_visible_code_artifacts(ctx: PaperGateContext) -> None:
    ctx.visible_code_artifacts = find_visible_code_artifact_references(
        ctx.expanded_main
    )


def reject_visible_code_artifacts(ctx: PaperGateContext) -> None:
    if ctx.visible_code_artifacts:
        ctx.problems.append(
            "manuscript exposes implementation symbols or artifact paths: "
            + ", ".join(ctx.visible_code_artifacts[:8])
        )


def detect_forbidden_simulation_label(ctx: PaperGateContext) -> None:
    ctx.forbidden_simulation_label_present = any(
        (
            marker.casefold() in ctx.normalized_manuscript
            for marker in FORBIDDEN_RENDERED_SIMULATION_LABELS
        )
    )


def reject_forbidden_simulation_label(ctx: PaperGateContext) -> None:
    if ctx.forbidden_simulation_label_present:
        ctx.problems.append("manuscript contains an internal evidence-status warning")


def validate_simulation_disclosure(ctx: PaperGateContext) -> None:
    if ctx.evidence_mode == "synthetic_preview":
        disclosure = simulation_disclosure_report(ctx.expanded_main)
        if (
            disclosure.get("count") != 1
            or disclosure.get("end_matter_count") != 1
            or disclosure.get("outside_end_matter_count") != 0
        ):
            ctx.problems.append(
                "simulation manuscript must contain exactly one final disclosure after the Conclusion and before the bibliography"
            )
        framing_hits = rendered_mode_framing_hits_outside_end_disclosure(
            ctx.expanded_main
        )
        if framing_hits:
            ctx.problems.append(
                "manuscript exposes simulation or evidence-mode framing outside the final disclosure: "
                + ", ".join(framing_hits[:6])
            )


def find_watermarks(ctx: PaperGateContext) -> None:
    ctx.watermark_commands = visible_watermark_commands(ctx.expanded_main)


def reject_watermarks(ctx: PaperGateContext) -> None:
    if ctx.watermark_commands:
        ctx.problems.append(
            "manuscript contains visible watermark or draft-stamp commands: "
            + ", ".join(ctx.watermark_commands[:4])
        )


def validate_latex_shell(ctx: PaperGateContext) -> None:
    if (
        "\\documentclass" not in ctx.main_text
        or "\\begin{document}" not in ctx.main_text
        or "\\end{document}" not in ctx.main_text
    ):
        ctx.problems.append("main.tex is not a complete LaTeX document")


def validate_draft_language(ctx: PaperGateContext) -> None:
    if ctx.host._paper_has_unfinished_draft_language(ctx.combined, ctx.evidence_mode):
        ctx.problems.append("paper contains placeholder or unfinished-draft language")


def find_title(ctx: PaperGateContext) -> None:
    ctx.title_match = re.search(
        "\\\\(?:title|icmltitle)\\{([^}]+)\\}", ctx.main_text, flags=re.DOTALL
    )


def validate_title(ctx: PaperGateContext) -> None:
    if not ctx.title_match or len(ctx.title_match.group(1).strip()) < 8:
        ctx.problems.append("paper title is missing or too short")
    elif re.search(
        "^(?:selected idea|untitled(?: paper| research)?|paper title|evidence-grounded research workflow)$",
        " ".join(ctx.title_match.group(1).split()),
        flags=re.IGNORECASE,
    ):
        ctx.problems.append(
            "paper title is generic and does not identify the accepted research idea"
        )


def find_abstract(ctx: PaperGateContext) -> None:
    ctx.abstract_match = re.search(
        "\\\\begin\\{abstract\\}(.*?)\\\\end\\{abstract\\}",
        ctx.expanded_main,
        flags=re.DOTALL,
    )


def normalize_abstract(ctx: PaperGateContext) -> None:
    ctx.abstract_text = (
        re.sub("\\\\[a-zA-Z]+\\{?|\\}", " ", ctx.abstract_match.group(1))
        if ctx.abstract_match
        else ""
    )


def validate_abstract(ctx: PaperGateContext) -> None:
    if len(" ".join(ctx.abstract_text.split())) < 220:
        ctx.problems.append("abstract is missing or too short (minimum 220 characters)")


def validate_document_length(ctx: PaperGateContext) -> None:
    if len(ctx.expanded_main.strip()) < 4000:
        ctx.problems.append(
            f"paper body is too short ({len(ctx.expanded_main.strip())} characters; minimum 4000)"
        )


def count_main_words(ctx: PaperGateContext) -> None:
    ctx.main_text_words = sum(
        (
            word_count(content)
            for path, content in ctx.source_text.items()
            if path.parent.name == "sections" and re.match("0[1-8]_", path.name)
        )
    )


def fallback_main_words(ctx: PaperGateContext) -> None:
    if not ctx.main_text_words:
        ctx.main_text_words = word_count(ctx.expanded_main)


def read_word_range(ctx: PaperGateContext) -> None:
    ctx.word_range = list(ctx.manuscript_profile.get("main_text_words") or [])


def validate_word_range(ctx: PaperGateContext) -> None:
    if len(ctx.word_range) == 2:
        minimum_words, maximum_words = (int(ctx.word_range[0]), int(ctx.word_range[1]))
        if ctx.main_text_words < minimum_words:
            ctx.problems.append(
                f"main text is too thin for the selected profile ({ctx.main_text_words} words; minimum {minimum_words})"
            )
        if ctx.main_text_words > maximum_words:
            ctx.problems.append(
                f"main text is too verbose for the selected profile ({ctx.main_text_words} words; maximum {maximum_words})"
            )


def locate_selected_contract(ctx: PaperGateContext) -> None:
    ctx.selected_contract_path = ctx.root / "ideas" / "SELECTED_IDEA.json"


def initialize_selected_contract(ctx: PaperGateContext) -> None:
    ctx.selected_contract: dict = {}


def load_selected_contract(ctx: PaperGateContext) -> None:
    if ctx.selected_contract_path.is_file():
        try:
            loaded_contract = json.loads(
                ctx.selected_contract_path.read_text(encoding="utf-8-sig")
            )
            ctx.selected_contract = (
                loaded_contract if isinstance(loaded_contract, dict) else {}
            )
        except (OSError, json.JSONDecodeError):
            ctx.problems.append("ideas/SELECTED_IDEA.json is not valid JSON")


def validate_selected_title(ctx: PaperGateContext) -> None:
    if ctx.selected_contract:
        publication = ctx.selected_contract.get("publication")
        publication = publication if isinstance(publication, dict) else {}
        accepted_title = str(publication.get("title") or "").strip()
        title_tokens = {
            token
            for token in re.findall("[A-Za-z0-9]{4,}", accepted_title.casefold())
            if token not in {"with", "from", "using", "based", "model", "research"}
        }
        paper_title_text = (
            ctx.title_match.group(1).casefold() if ctx.title_match else ""
        )
        if title_tokens and (
            not any((token in paper_title_text for token in title_tokens))
        ):
            ctx.problems.append(
                "paper title is not traceable to the accepted selected-idea contract"
            )
        ctx.method_source = next(
            (
                content
                for path, content in ctx.source_text.items()
                if path.parent.name == "sections" and re.match("03_", path.name)
            ),
            "",
        )


def validate_selected_mechanisms(ctx: PaperGateContext) -> None:
    if ctx.selected_contract:
        if not ctx.method_source:
            method_match = re.search(
                "\\\\section\\*?\\{[^}]*(?:method|approach|system\\s+design|study\\s+design|framework|model|方法|系统设计|研究设计)[^}]*\\}(.*?)(?=\\\\section\\*?\\{|\\Z)",
                ctx.expanded_main,
                flags=re.IGNORECASE | re.DOTALL,
            )
            ctx.method_source = method_match.group(1) if method_match else ""
        method_text = re.sub("\\\\[A-Za-z]+\\{?|\\}", " ", ctx.method_source)
        method_contract = {}
        method_contract_path = ctx.root / "experiments" / "METHOD_CONTRACT.json"
        if method_contract_path.is_file():
            try:
                loaded_method_contract = json.loads(
                    method_contract_path.read_text(encoding="utf-8-sig")
                )
                if isinstance(loaded_method_contract, dict):
                    method_contract = loaded_method_contract
            except (OSError, UnicodeError, json.JSONDecodeError):
                method_contract = {}
        for mechanism in ctx.selected_contract.get("mechanisms") or []:
            if not isinstance(mechanism, dict) or not mechanism.get("required", True):
                continue
            mechanism_name = " ".join(str(mechanism.get("publication_name") or "").split())
            mechanism_id = str(mechanism.get("id") or "").strip()
            coverage = next(
                (
                    item
                    for item in method_contract.get("mechanism_coverage") or []
                    if isinstance(item, dict)
                    and str(
                        item.get("idea_mechanism_id") or item.get("mechanism_id") or ""
                    ).strip()
                    == mechanism_id
                ),
                {},
            )
            semantic_aliases = [
                str(mechanism.get("publication_description") or ""),
                str(mechanism.get("publication_evaluation") or ""),
                str(coverage.get("required_observation") or ""),
                str(coverage.get("planned_intervention") or ""),
                *[
                    str(item.get("description") or "")
                    for item in method_contract.get("implementation_checks") or []
                    if isinstance(item, dict)
                    and mechanism_id
                    and (
                        mechanism_id.casefold() in str(item.get("id") or "").casefold()
                    )
                ],
            ]
            if not ctx.host._paper_covers_mechanism(
                mechanism_name, method_text, semantic_aliases
            ):
                ctx.problems.append(
                    f"method section does not name required accepted mechanism: {mechanism_name}"
                )


def count_sections(ctx: PaperGateContext) -> None:
    ctx.section_count = len(re.findall("\\\\section\\*?\\{", ctx.expanded_main))


def collect_figure_blocks(ctx: PaperGateContext) -> None:
    ctx.figure_blocks = re.findall(
        "\\\\begin\\{figure\\*?\\}.*?\\\\end\\{figure\\*?\\}",
        ctx.expanded_main,
        flags=re.DOTALL,
    )


def collect_table_blocks(ctx: PaperGateContext) -> None:
    ctx.table_blocks = re.findall(
        "\\\\begin\\{table\\*?\\}.*?\\\\end\\{table\\*?\\}",
        ctx.expanded_main,
        flags=re.DOTALL,
    )


def collect_labels(ctx: PaperGateContext) -> None:
    ctx.included_labels = set(re.findall("\\\\label\\{([^}]+)\\}", ctx.expanded_main))


def locate_figure_manifest(ctx: PaperGateContext) -> None:
    ctx.manifest_path = figure_artifact_registry.manifest_path(ctx.root / "figures")


def load_figure_manifest(ctx: PaperGateContext) -> None:
    ctx.manifest = (
        figure_artifact_registry.reconcile(ctx.root / "figures")
        if ctx.manifest_path.exists()
        else {"figures": []}
    )


def initialize_manifest_outputs(ctx: PaperGateContext) -> None:
    ctx.manifest_outputs: list[Path] = []


def collect_manifest_outputs(ctx: PaperGateContext) -> None:
    for item in ctx.manifest.get("figures", []):
        value = item.get("output_path")
        if not value or not item.get("paper_ready"):
            continue
        candidate = Path(value)
        ctx.manifest_outputs.append(
            (candidate if candidate.is_absolute() else ctx.root / candidate).resolve()
        )


def initialize_figure_graphics(ctx: PaperGateContext) -> None:
    ctx.figure_graphics_by_label: dict[str, set[Path]] = {}


def map_figure_graphics(ctx: PaperGateContext) -> None:
    for block in ctx.figure_blocks:
        label_match = re.search("\\\\label\\{(fig:[^}]+)\\}", block)
        if not label_match:
            continue
        label_graphics = ctx.figure_graphics_by_label.setdefault(
            label_match.group(1), set()
        )
        for raw_path in re.findall(
            "\\\\includegraphics\\*?(?:\\[[^\\]]*\\])?\\{([^}]+)\\}", block
        ):
            resolved = resolve_graphic_path(
                raw_path, ctx.paper_root, ctx.root, ctx.manifest_outputs
            )
            if resolved:
                from ..services.paper_print_projection import canonical_print_graphic
                try:
                    label_graphics.add(canonical_print_graphic(ctx.root, resolved))
                except ValueError as error:
                    ctx.problems.append(str(error))


def select_included_tables(ctx: PaperGateContext) -> None:
    ctx.included_table_entries = [
        item
        for item in ctx.table_entries
        if str(item.get("label") or "") in ctx.included_labels
    ]


def canonicalize_table_roles(ctx: PaperGateContext) -> None:
    ctx.included_table_roles = canonical_roles(
        [
            *(
                str(item.get("scientific_role") or "")
                for item in ctx.included_table_entries
            ),
            *(str(item.get("id") or "") for item in ctx.included_table_entries),
        ],
        TABLE_ROLE_ALIASES,
    )


def find_missing_table_roles(ctx: PaperGateContext) -> None:
    ctx.missing_included_table_roles = sorted(
        set(ctx.manuscript_profile.get("table_contract", {}).get("required_roles", []))
        - ctx.included_table_roles
    )


def reject_missing_table_roles(ctx: PaperGateContext) -> None:
    if ctx.missing_included_table_roles:
        ctx.problems.append(
            "core scientific tables exist in metadata but are not included in the paper: "
            + ", ".join(ctx.missing_included_table_roles)
        )


def select_figure_assets(ctx: PaperGateContext) -> None:
    ctx.included_figure_assets = [
        item
        for item in ctx.asset_plan.get("assets", [])
        if isinstance(item, dict)
        and item.get("kind") == "figure"
        and (str(item.get("label") or "") in ctx.included_labels)
    ]


def initialize_structural_assets(ctx: PaperGateContext) -> None:
    ctx.structural_preview_assets: list[dict[str, Any]] = []


def synthetic_asset_manifest(ctx: PaperGateContext) -> None:
    if ctx.evidence_mode == "synthetic_preview":
        ctx.expected_synthetic_ids = {
            str(item.get("id") or "").strip()
            for item in ctx.asset_plan.get("assets", [])
            if isinstance(item, dict)
            and item.get("kind") == "figure"
            and (
                str(item.get("evidence_status") or "").casefold() == "synthetic_preview"
            )
            and str(item.get("id") or "").strip()
        }


def _structural_asset_paths(
    ctx: PaperGateContext,
    entry: dict[str, Any],
    metadata: dict[str, Any],
    label: str,
) -> tuple[Path, str, Path] | None:
    output_value = str(entry.get("output_path") or "").strip()
    source_value = str(entry.get("source_path") or "").strip()
    if not label or not output_value or not source_value:
        return None
    output_path = Path(output_value)
    output_path = (
        output_path if output_path.is_absolute() else ctx.root / output_path
    ).resolve()
    source_path = Path(source_value)
    source_path = (
        source_path if source_path.is_absolute() else ctx.root / source_path
    ).resolve()
    try:
        output_relative = output_path.relative_to(ctx.root).as_posix()
        source_relative = source_path.relative_to(ctx.root).as_posix()
    except ValueError:
        return None
    if not output_relative.startswith(
        "figures/simulated/"
    ) or not source_relative.startswith("figures/simulated/"):
        return None
    if output_path not in ctx.figure_graphics_by_label.get(label, set()):
        return None
    manifest_value = str(metadata.get("simulation_manifest") or "").strip()
    manifest_hash = str(metadata.get("simulation_manifest_sha256") or "").strip()
    if not manifest_value or not manifest_hash:
        return None
    manifest_path = Path(manifest_value)
    manifest_path = (
        manifest_path if manifest_path.is_absolute() else ctx.root / manifest_path
    ).resolve()
    return output_path, output_relative, manifest_path


def _validated_simulation_manifest(
    ctx: PaperGateContext,
    path: Path,
    expected_hash: str,
) -> dict[str, Any] | None:
    try:
        relative = path.relative_to(ctx.root).as_posix()
    except ValueError:
        return None
    if (
        relative != "experiments/results/simulated/SIMULATION_MANIFEST.json"
        or not path.is_file()
    ):
        return None
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected_hash:
        return None
    try:
        payload = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    if payload.get("explicit_user_mode") != "synthetic_preview":
        return None
    if payload.get("evidence_status") != "synthetic_preview":
        return None
    return payload if payload.get("manuscript_eligible") is True else None


def _manifest_binds_output(
    manifest: dict[str, Any],
    semantic_key: str,
    relative: str,
    sha256: str,
) -> bool:
    for record in manifest.get("figure_files", []):
        if not isinstance(record, dict) or str(record.get("id") or "") != semantic_key:
            continue
        outputs = dict(record.get("outputs") or {})
        hashes = dict(record.get("output_sha256") or {})
        if any(
            str(value) == relative and str(hashes.get(kind) or "") == sha256
            for kind, value in outputs.items()
        ):
            return True
    return False


def _collect_structural_asset_entry(ctx: PaperGateContext, entry: Any) -> None:
    if not isinstance(entry, dict):
        return
    metadata = dict(entry.get("metadata") or {})
    if (
        str(metadata.get("evidence_status") or "").casefold() != "synthetic_preview"
        or entry.get("paper_ready") is not True
        or metadata.get("paper_selected") is not True
        or (metadata.get("manuscript_eligible") is not True)
        or (metadata.get("submission_eligible") is not False)
        or (
            str(metadata.get("provenance_kind") or "")
            != "deterministic_simulation_preview"
        )
        or (
            str(metadata.get("disclosure") or "").strip()
            != "SIMULATED DATA -- NOT EXPERIMENTAL RESULTS"
        )
    ):
        return
    label = str(metadata.get("label") or "").strip()
    paths = _structural_asset_paths(ctx, entry, metadata, label)
    if paths is None:
        return
    _, output_relative, simulation_manifest_path = paths
    simulation_manifest = _validated_simulation_manifest(
        ctx,
        simulation_manifest_path,
        str(metadata.get("simulation_manifest_sha256") or "").strip(),
    )
    if simulation_manifest is None:
        return
    semantic_key = str(metadata.get("semantic_key") or entry.get("id") or "").strip()
    output_sha256 = str(entry.get("output_sha256") or "")
    if not _manifest_binds_output(
        simulation_manifest, semantic_key, output_relative, output_sha256
    ):
        return
    ctx.structural_preview_assets.append(
        {
            "id": semantic_key,
            "kind": "figure",
            "scientific_role": str(metadata.get("scientific_role") or ""),
            "label": label,
            "evidence_status": "synthetic_preview",
            "provenance_kind": "deterministic_simulation_preview",
            "structural_preview_only": True,
        }
    )


def synthetic_asset_rows(ctx: PaperGateContext) -> None:
    if ctx.evidence_mode == "synthetic_preview":
        for entry in ctx.manifest.get("figures", []):
            _collect_structural_asset_entry(ctx, entry)
