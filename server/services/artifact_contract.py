"""Current producer output paths shared by authoring sessions and write policy.

There is no post-write migration. A producer writes its canonical output or
receives a path error; consumers validate the unchanged, registered artifacts.
"""

import json
import re
from pathlib import Path, PurePosixPath

from .project_scaffold import WORKFLOW_ARTIFACT_CONTRACT, get_workflow_artifact_contract
from .research_contract_versions import CURRENT_RESEARCH_ARTIFACT_SCHEMAS


def declared_skill_outputs(frontmatter: str) -> list[str]:
    """Read an explicit JSON/YAML output list, never guess paths from prose.

    No declaration means no statically declared output. Dynamic assets remain
    scoped by the skill's bounded invocation and the current producer contract.
    """
    match = re.search(r"(?m)^artifact-outputs:\s*(.+)$", frontmatter)
    if not match:
        return []
    try:
        values = json.loads(match.group(1))
    except json.JSONDecodeError as error:
        raise ValueError("artifact-outputs must be an inline JSON list") from error
    if not isinstance(values, list) or any(not isinstance(value, str) for value in values):
        raise ValueError("artifact-outputs must contain relative path strings")
    for value in values:
        path = PurePosixPath(value)
        if not value or path.is_absolute() or ".." in path.parts or "\\" in value or ":" in value:
            raise ValueError(f"Invalid declared artifact output: {value}")
        validation_root = Path.cwd().resolve()
        path_error = artifact_write_error(validation_root, validation_root / value)
        if path_error:
            raise ValueError(path_error)
    return list(dict.fromkeys(values))


def declared_skill_artifact_contracts(frontmatter: str) -> dict[str, int]:
    """Parse explicit output schema ownership from one skill frontmatter."""
    match = re.search(r"(?m)^artifact-contracts:\s*(.+)$", frontmatter)
    if not match:
        return {}
    try:
        values = json.loads(match.group(1))
    except json.JSONDecodeError as error:
        raise ValueError("artifact-contracts must be an inline JSON object") from error
    if not isinstance(values, dict):
        raise ValueError("artifact-contracts must map relative paths to schema integers")
    contracts: dict[str, int] = {}
    for raw_path, raw_schema in values.items():
        if not isinstance(raw_path, str) or not isinstance(raw_schema, int):
            raise ValueError("artifact-contracts must map relative paths to schema integers")
        path = PurePosixPath(raw_path)
        if not raw_path or path.is_absolute() or ".." in path.parts or "\\" in raw_path:
            raise ValueError(f"Invalid artifact contract path: {raw_path}")
        if raw_schema < 1:
            raise ValueError(f"Invalid artifact contract schema for {raw_path}: {raw_schema}")
        contracts[raw_path] = raw_schema
    return contracts


def validate_skill_artifact_contracts(
    outputs: list[str], contracts: dict[str, int],
) -> None:
    """Require every versioned skill output to match the runtime contract."""
    output_set = set(outputs)
    undeclared = sorted(set(contracts) - output_set)
    if undeclared:
        raise ValueError(
            "artifact-contracts references undeclared output(s): "
            + ", ".join(undeclared)
        )
    expected = {
        path: schema
        for path, schema in CURRENT_RESEARCH_ARTIFACT_SCHEMAS.items()
        if path in output_set
    }
    missing = sorted(set(expected) - set(contracts))
    if missing:
        raise ValueError(
            "versioned artifact output(s) lack artifact-contracts: "
            + ", ".join(missing)
        )
    mismatched = [
        f"{path}: declared={contracts[path]}, current={schema}"
        for path, schema in expected.items()
        if contracts.get(path) != schema
    ]
    if mismatched:
        raise ValueError("skill artifact schema mismatch: " + "; ".join(mismatched))
    unknown = sorted(set(contracts) - set(CURRENT_RESEARCH_ARTIFACT_SCHEMAS))
    if unknown:
        raise ValueError(
            "artifact-contracts has no runtime schema owner: " + ", ".join(unknown)
        )


def validate_skill_artifact_contract_content(content: str) -> None:
    """Validate a complete SKILL.md immediately before model invocation."""
    frontmatter = re.match(
        r"^---\s*\n(.*?)\n---\s*(?:\n|$)",
        str(content or ""),
        re.DOTALL,
    )
    frontmatter_text = frontmatter.group(1) if frontmatter else ""
    outputs = declared_skill_outputs(frontmatter_text)
    contracts = declared_skill_artifact_contracts(frontmatter_text)
    validate_skill_artifact_contracts(outputs, contracts)


def render_artifact_contract(project_path: str | Path, node_id: str = "") -> str:
    """Scope a producer to the same paths used by deterministic acceptance."""
    node_ids = [node_id] if node_id in WORKFLOW_ARTIFACT_CONTRACT else list(WORKFLOW_ARTIFACT_CONTRACT)
    lines = [
        "## Current MERAK producer artifact contract",
        f"Project root: {Path(project_path).expanduser().resolve()}",
        "Write outputs directly at their canonical paths. No consumer moves, copies, or deduplicates misplaced outputs.",
        "Read/Write/Edit paths resolve against the project root. A shell's cwd does not change their path resolution.",
        "The list identifies stage ownership, not a request to create every stage's artifacts.",
        "Follow this invocation's stage/target scope. Keep distinct supporting artifacts inside their owning directory.",
        "Use designated runtime tools for runtime-owned manifests, hashes, and status; do not author those fields yourself.",
    ]
    for phase in node_ids:
        contract = get_workflow_artifact_contract(project_path, phase)
        lines.append(f"- {phase}: " + ", ".join(contract["required"]))
    owned_outputs = {
        raw
        for phase in node_ids
        for raw in WORKFLOW_ARTIFACT_CONTRACT[phase]["required"]
    }
    for relative, schema in CURRENT_RESEARCH_ARTIFACT_SCHEMAS.items():
        if relative in owned_outputs:
            lines.append(
                f"- Required current schema: {relative} = {schema}. "
                "Older schemas and compatibility version fields are unsupported."
            )
    lines.extend([
        "Compact idea summaries use ideas/COMPACT_IDEA_CANDIDATES.md, never replace ideas/ideas.md.",
        "Refinement history uses experiments/refinement/; its final proposal belongs in ideas/FINAL_PROPOSAL.md.",
        "If a canonical upstream artifact is missing, report its owner/path; do not probe or migrate historical equivalents.",
        "Declared research inputs remain read-only unless the current operation explicitly owns their revision.",
    ])
    return "\n".join(lines)


def artifact_write_error(project_root: Path, target: Path) -> str:
    """Reject incompatible destinations without moving or changing any file.

    Reads are unaffected. This supplements the project-containment policy,
    which the caller must apply before invoking this current-path check.
    """
    relative = target.relative_to(project_root).as_posix()
    if relative.casefold() == 'figures/figure_specs.json':
        return (
            'ARTIFACT_CONTRACT_ERROR: FIGURE_SPECS.json is runtime-owned and '
            'already derived from the complete scientific asset plan. Read it; '
            'do not replace its schema, labels, producers, or asset list. '
            'Generate only the assigned model-owned asset using generate_figure.'
        )
    producer_error = deterministic_figure_source_write_error(project_root, target)
    if producer_error:
        return producer_error
    parts = relative.casefold().split("/")
    retired_names = {"idea_report.md", "idea_candidates.md", "experiment_results.md"}
    invalid_namespace = parts[0] in {"idea-stage", "refine-logs", "results"}
    if invalid_namespace or parts[-1] in retired_names:
        return f"ARTIFACT_CONTRACT_ERROR: unsupported output path {relative}. Write directly to the current producer contract; no path migration is performed."
    # Restrict registered machine/report filenames, not arbitrary scientific
    # supporting files. Local bibliography copies and per-round manuscripts are
    # legitimate, so main.tex/main.pdf/references.bib are not global name locks.
    registered: dict[str, set[str]] = {}
    for contract in WORKFLOW_ARTIFACT_CONTRACT.values():
        for raw in contract["required"]:
            path = Path(raw)
            if path.suffix and path.name not in {"main.tex", "main.pdf", "references.bib"}:
                registered.setdefault(path.name.casefold(), set()).add(raw.casefold())
    expected = registered.get(parts[-1])
    if expected and relative.casefold() not in expected:
        return f"ARTIFACT_CONTRACT_ERROR: {relative} is not a registered output. Write to: {', '.join(sorted(expected))}."
    if len(parts) == 1 and parts[-1] in {"main.tex", "main.pdf", "novelty_report.md"}:
        return f"ARTIFACT_CONTRACT_ERROR: root-level {relative} is not a stage output; use the current paper/slides/ideas contract."
    return ""


def deterministic_figure_source_write_error(
    project_root: Path, target: Path,
) -> str:
    """Protect runtime-generated figure sources from model-authored edits."""
    figures = (project_root / "figures").resolve()
    try:
        target.relative_to(figures)
    except ValueError:
        return ""
    specs = project_root / "figures/FIGURE_SPECS.json"
    if specs.is_file():
        try:
            payload = json.loads(specs.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            payload = {}
        for spec in payload.get("figures") or []:
            if (
                isinstance(spec, dict)
                and spec.get("producer_kind") == "deterministic"
                and target.stem == str(spec.get("id") or "")
            ):
                return (
                    f"ARTIFACT_CONTRACT_ERROR: {target.stem} is owned by a "
                    "deterministic producer. Repair its typed FIGURE_SPECS input "
                    "and invoke the owner; do not edit the generated source directly."
                )
    manifest = project_root / "figures/FIGURE_MANIFEST.json"
    if not manifest.is_file():
        return ""
    try:
        payload = json.loads(manifest.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return ""
    for item in payload.get("figures") or []:
        if not isinstance(item, dict):
            continue
        metadata = item.get("metadata")
        metadata = metadata if isinstance(metadata, dict) else {}
        if metadata.get("producer_kind") != "deterministic":
            continue
        source_value = str(item.get("source_path") or "").strip()
        if not source_value:
            continue
        source = Path(source_value).expanduser()
        source = source if source.is_absolute() else project_root / source
        if source.resolve() == target.resolve():
            asset_id = str(item.get("id") or metadata.get("semantic_key") or "asset")
            return (
                f"ARTIFACT_CONTRACT_ERROR: {asset_id} is owned by a deterministic "
                "producer. Repair its typed FIGURE_SPECS input and invoke the owner; "
                "do not edit the generated source directly."
            )
    return ""
