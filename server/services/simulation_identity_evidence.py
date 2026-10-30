"""Explain locally computed byte and scientific identities already cited by review inputs."""

import hashlib
import json
import re
from pathlib import Path

from .paper_artifacts import simulation_manifest_semantic_hash


def simulation_identity_evidence(root: Path) -> str:
    """Report hash comparisons only; no extra scientific source contents leave the project."""
    relative = 'experiments/results/simulated/SIMULATION_MANIFEST.json'
    path = root / relative
    if not path.is_file():
        return ''
    raw = path.read_bytes()
    byte_hash = hashlib.sha256(raw).hexdigest()
    semantic_hash = simulation_manifest_semantic_hash(json.loads(raw))
    analysis = root / 'experiments/results/analysis.md'
    declared = re.findall(r'semantic SHA-256\s+`([0-9a-f]{64})`', analysis.read_text(encoding='utf-8')) if analysis.is_file() else []
    registry = root / 'figures/FIGURE_MANIFEST.json'
    bindings = []
    if registry.is_file():
        for entry in json.loads(registry.read_bytes()).get('figures', []):
            pin = (entry.get('metadata') or {}).get('simulation_manifest_sha256')
            if pin:
                bindings.append({'figure_id': entry.get('id'), 'byte_sha256': pin, 'matches_current_file': pin == byte_hash})
    value = {'manifest': relative, 'byte_sha256': byte_hash, 'semantic_sha256': semantic_hash,
        'byte_algorithm': 'SHA-256 of exact file bytes, including presentation metadata and timestamps',
        'semantic_algorithm': 'SHA-256 of canonical UTF-8 scientific JSON projection; excludes renderer metadata, '
            'timestamps and output hashes while preserving scientific records and data-file hashes',
        'analysis_semantic_hashes': declared, 'analysis_matches_current_semantics': bool(declared) and all(x == semantic_hash for x in declared),
        'figure_manifest_byte_bindings': bindings,
        'scope': 'Integrity identifiers only; neither hash establishes scientific validity or independent reconstruction.'}
    return ('\nRuntime-computed identity comparisons for identifiers already present in the review packet:\n'
            + json.dumps(value, ensure_ascii=False, indent=2)
            + '\nReport any false match or changed scientific record. Different byte/semantic hashes alone are expected, '
              'not a provenance break. Independently assess all scientific claims.\n')
