"""Expose actual read-only provenance checks without sending additional scientific sources."""

import hashlib
import json
from pathlib import Path


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def freeze_source_facts(root: Path) -> dict:
    from ..services.paper_scientific_freeze import HASH_MODE, scientific_freeze_inputs
    path = root / 'paper/SCIENTIFIC_FREEZE.json'
    if not path.is_file():
        return {'present': False}
    record = json.loads(path.read_bytes())
    actual = scientific_freeze_inputs(root)
    recorded = record.get('inputs') or {}
    same_inventory = set(recorded) == set(actual)
    comparisons = [{'path': name, 'recorded_scientific_hash': recorded.get(name),
        'current_scientific_hash': digest, 'current_byte_hash': _sha(root / name) if (root / name).is_file() else '<missing>',
        'scientific_match': recorded.get(name) == digest} for name, digest in actual.items()]
    return {'present': True, 'hash_mode': record.get('input_hash_mode'),
        'valid_source_binding': record.get('schema_version') == 1 and record.get('input_hash_mode') == HASH_MODE
            and same_inventory and all(row['scientific_match'] for row in comparisons),
        'same_source_inventory': same_inventory, 'comparisons': comparisons,
        'hash_definition': 'Ordinary JSON sources use stable_source_hash: parse JSON, recursively remove builder '
            'timestamps, JSON serialize ensure_ascii=False and sort_keys=True, then SHA-256 UTF-8 bytes. '
            'Derived manifests use their declared semantic projection. These hashes are not raw file-byte hashes.'}


def table_projection_facts(root: Path) -> dict:
    from ..services.simulation_table_projection_binding import (
        verify_simulation_table_projection, SIMULATION_MANIFEST, CANONICAL_TABLE, PUBLICATION_BINDING,
    )
    manifest = root / SIMULATION_MANIFEST
    if not manifest.is_file():
        return {'present': False}
    payload = json.loads(manifest.read_bytes())
    try:
        proof = verify_simulation_table_projection(root, payload)
    except (ValueError, OSError, KeyError, TypeError) as error:
        return {'present': True, 'valid': False, 'error': str(error)}
    return {'present': True, 'valid': True, 'original_source_sha256': payload.get('paper_table_sha256'),
        'current_table_sha256': _sha(root / CANONICAL_TABLE), 'projection_proof': PUBLICATION_BINDING if proof else None,
        'proof_checks': 'Original text matches frozen source hash; data and figure hashes remain unchanged; '
            'current table exactly equals the current producer projection, preserving every scientific row.',
        'interpretation': 'A verified paper-owned projection may differ bytewise from its original source; '
            'the frozen source hash must not be overwritten to hide that distinction.'}


def print_projection_facts(root: Path) -> dict:
    from ..services.paper_print_projection import validate_print_projection
    path = root / 'paper/derived-figures/PRINT_PROJECTION.json'
    if not path.is_file():
        return {'present': False}
    issues = validate_print_projection(root)
    proof = json.loads(path.read_bytes())
    return {'present': True, 'valid': not issues, 'issues': issues,
        'source_pairs': [{key: row.get(key) for key in (
            'original_path', 'original_sha256', 'output_path', 'output_sha256')}
            for row in proof.get('sources', [])],
        'proof_checks': 'Exact source-bound print transformation, canonical inputs, derived variants and output hashes.',
        'interpretation': 'Compare an original hash to its original_path and a derived hash to its output_path; '
            'different source and derived include hashes are expected only when this validation passes.'}


def provenance_context(root: Path, skill: str) -> str:
    """Keep checks distinct from scientific validity; failures remain explicit audit evidence."""
    if skill not in {'result-to-claim', 'paper-claim-audit', 'experiment-audit'}:
        return ''
    facts = {'scientific_freeze_sources': freeze_source_facts(root),
        'table_projection': table_projection_facts(root), 'print_projection': print_projection_facts(root)}
    return ('\n## Runtime-owned provenance checks\n' + json.dumps(facts, ensure_ascii=False, indent=2)
        + '\nThese are current deterministic checks, not scientific acceptance. Preserve every actual failed check. '
          'Do not infer corruption by comparing raw file hashes to scientific hashes, or original hashes to '
          'verified derived outputs. Never ask a model to rewrite hashes, statuses or frozen experiments. '
          'If you identify a concrete integrity defect beyond these checks, report the exact field and evidence.\n')
