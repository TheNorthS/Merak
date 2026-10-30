"""Different hash domains are explained, actual mismatches remain visible."""

import hashlib
import json

from server.services.paper_artifacts import simulation_manifest_semantic_hash
from server.services.simulation_identity_evidence import simulation_identity_evidence


def seed(root):
    manifest = root/'experiments/results/simulated/SIMULATION_MANIFEST.json'
    manifest.parent.mkdir(parents=True)
    payload = {'schema': 11, 'generated_at': 123, 'simulation_seed': '1729',
        'data_files': [{'path': 'data.csv', 'sha256': 'frozen-data'}]}
    manifest.write_text(json.dumps(payload))
    analysis = root/'experiments/results/analysis.md'
    analysis.write_text(f'semantic SHA-256 `{simulation_manifest_semantic_hash(payload)}`')
    registry = root/'figures/FIGURE_MANIFEST.json';registry.parent.mkdir()
    registry.write_text(json.dumps({'figures': [{'id': 'f', 'metadata': {
        'simulation_manifest_sha256': hashlib.sha256(manifest.read_bytes()).hexdigest()}}]}))
    return manifest, analysis


def test_byte_and_semantic_hashes_match_their_actual_domains_without_equating_them(tmp_path):
    manifest, _ = seed(tmp_path)
    text = simulation_identity_evidence(tmp_path)
    payload = json.loads(manifest.read_bytes())
    assert hashlib.sha256(manifest.read_bytes()).hexdigest() != simulation_manifest_semantic_hash(payload)
    assert '"analysis_matches_current_semantics": true' in text
    assert '"matches_current_file": true' in text
    assert 'neither hash establishes scientific validity' in text
    assert 'frozen-data' not in text


def test_real_source_mismatch_is_reported_without_rebinding(tmp_path):
    manifest, analysis = seed(tmp_path)
    original = analysis.read_bytes()
    payload = json.loads(manifest.read_bytes());payload['simulation_seed'] = 'changed'
    manifest.write_text(json.dumps(payload))
    text = simulation_identity_evidence(tmp_path)
    assert '"analysis_matches_current_semantics": false' in text
    assert '"matches_current_file": false' in text
    assert analysis.read_bytes() == original
