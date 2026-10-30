"""Declare all current scientific and code inputs consumed by narrative truth rendering."""

from pathlib import Path
import ast
import hashlib
import json

from ..utils.runtime_source_root import server_source_root


def narrative_implementation_sha256() -> str:
    root = server_source_root() / "services"
    names = ("scientific_narrative.py", "narrative_rendering.py", "narrative_evidence.py",
             "narrative_source_bindings.py", "simulation_claim_decision_report.py",
             "simulation_claim_decisions.py", "protocol_conformance.py")
    digest = hashlib.sha256()
    for name in names:
        digest.update(name.encode())
        digest.update((root / name).read_bytes())
    # Claim reporting imports this one schema constant. Manuscript disclosures,
    # captions and renderer policy are downstream and cannot invalidate prose.
    digest.update(_manifest_schema_dependency(root / 'simulation_policy.py'))
    return digest.hexdigest()


def _manifest_schema_dependency(path: Path) -> bytes:
    tree = ast.parse(path.read_text(encoding='utf-8-sig'))
    values = [node.value for node in tree.body if isinstance(node, ast.Assign)
              and any(isinstance(target, ast.Name) and target.id == 'SIMULATION_MANIFEST_SCHEMA'
                      for target in node.targets)]
    if len(values) != 1:
        raise ValueError('Narrative requires one explicit simulation manifest schema dependency')
    value = ast.literal_eval(values[0])
    if type(value) is not int or value < 1:
        raise ValueError('Simulation manifest schema must be a positive integer')
    return f'simulation_policy.py:SIMULATION_MANIFEST_SCHEMA={value}'.encode()


def narrative_scientific_sources(root: Path, initial: list[Path]) -> list[Path]:
    """Missing ledgers remain explicit dependencies, not evidence of readiness."""
    paths = [*initial, root / "experiments/results/CLAIM_DECISIONS.json",
             root / "experiments/PROTOCOL_CONFORMANCE.json", root / "experiments/EXPERIMENT_PLAN.md",
             root / "experiments/RUN_SPEC.json"]
    for directory, suffixes in (("experiments/src", {".py"}), ("experiments/configs", {".yaml", ".yml", ".json"})):
        paths.extend(path for path in (root / directory).rglob("*") if path.is_file() and path.suffix in suffixes)
    manifest = root / "experiments/results/simulated/SIMULATION_MANIFEST.json"
    try:
        payload = json.loads(manifest.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        payload = {}
    if isinstance(payload, dict):
        paths.extend(root / item["path"] for item in payload.get("data_files") or []
                     if isinstance(item, dict) and isinstance(item.get("path"), str))
    if any(not path.resolve().is_relative_to(root.resolve()) for path in paths):
        raise ValueError("Narrative evidence source inventory leaves its project")
    return sorted(set(paths), key=lambda path: path.as_posix())
