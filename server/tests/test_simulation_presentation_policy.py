"""Scenario manuscript eligibility cannot imply empirical or submission evidence."""

import json

import pytest

from server.services.simulation_presentation_policy import simulation_presentation_fields
from server.services.simulation_presentation_correction import correct_simulation_presentation
from server.services.scientific_asset_plan import _evidence
from server.tests.test_simulation_publication_attestation import _bundle, _files


def test_scenario_metadata_preserves_values_and_never_claims_population_confidence():
    source = {'description': 'Primary comparison with 95% confidence intervals.', 'submission_eligible': True,
              'metric': 0.73, 'label': 'fig:result', 'uncertainty_encoding': '95% confidence intervals'}
    projected = {**source, **simulation_presentation_fields(source)}
    assert projected['manuscript_eligible'] and not projected['submission_eligible']
    assert 'population confidence coverage' in projected['description']
    assert '95% confidence intervals' not in projected['description']
    assert projected['metric'] == source['metric'] and projected['label'] == source['label']
    assert not _evidence('synthetic_preview', [], [], [], [])['submission_eligible']
    assert _evidence('executed', [object()], [], [], [])['submission_eligible']


def test_explicit_metadata_correction_archives_original_and_preserves_source_bytes(tmp_path, monkeypatch):
    manifest, _ = _bundle(tmp_path, monkeypatch)
    payload = json.loads(manifest.read_bytes())
    payload.update(manuscript_eligible=True, submission_eligible=True)
    # Changing the setup manifest requires re-pinning its fixture registrations.
    from server.services.figure_artifacts import figure_artifact_registry
    import hashlib
    manifest.write_text(json.dumps(payload))
    registry_path = tmp_path / 'figures/FIGURE_MANIFEST.json'
    registry = figure_artifact_registry.load(tmp_path / 'figures')
    for item in registry['figures']:
        item['metadata']['simulation_manifest_sha256'] = hashlib.sha256(manifest.read_bytes()).hexdigest()
    registry_path.write_text(json.dumps(registry))
    before = _files(tmp_path)
    result = correct_simulation_presentation(tmp_path)
    assert result['data_and_rendered_files_unchanged'] and not result['generation_executed']
    assert json.loads(manifest.read_bytes())['submission_eligible'] is False
    archive = tmp_path / '.merak/repair-history/simulation-presentation' / result['previous_manifest_sha256']
    assert (archive / manifest.relative_to(tmp_path)).read_bytes() == before[manifest]
    for path, raw in before.items():
        if path.name not in {'SIMULATION_MANIFEST.json', 'FIGURE_MANIFEST.json', 'FIGURE_MANIFEST.md'}:
            assert path.read_bytes() == raw


def test_corrupt_source_blocks_correction_before_writing(tmp_path, monkeypatch):
    _manifest, figures = _bundle(tmp_path, monkeypatch)
    (tmp_path / figures[0]['source']).write_text('changed source')
    before = _files(tmp_path)
    with pytest.raises(ValueError, match='hash mismatch'):
        correct_simulation_presentation(tmp_path)
    assert _files(tmp_path) == before


def test_registry_failure_rolls_back_manifests(tmp_path, monkeypatch):
    _bundle(tmp_path, monkeypatch)
    from server.services.figure_artifacts import figure_artifact_registry
    before = _files(tmp_path)
    def fail(**kwargs):
        raise OSError('write failed')
    monkeypatch.setattr(figure_artifact_registry, 'record', fail)
    with pytest.raises(OSError, match='write failed'):
        correct_simulation_presentation(tmp_path)
    assert all(path.read_bytes() == raw for path, raw in before.items())


def test_planned_manifest_is_rebound_without_changing_generation_inputs(tmp_path, monkeypatch):
    import hashlib
    from server.services.figure_artifacts import figure_artifact_registry
    from server.services.planned_simulation_bindings import PLANNED_SIMULATION_MANIFEST, load_planned_simulation_binding
    manifest, figures = _bundle(tmp_path, monkeypatch)
    planned = tmp_path / PLANNED_SIMULATION_MANIFEST
    planned.parent.mkdir(parents=True)
    payload = {'schema': 5, 'input_bundle_sha256': 'immutable-input-id', 'methods': ['unchanged'],
        'simulation_manifest': manifest.relative_to(tmp_path).as_posix(),
        'simulation_manifest_sha256': hashlib.sha256(manifest.read_bytes()).hexdigest(),
        'figures': figure_artifact_registry.load(tmp_path / 'figures')['figures'], 'submission_eligible': True}
    planned.write_text(json.dumps(payload))
    correct_simulation_presentation(tmp_path)
    observed = json.loads(planned.read_bytes())
    assert observed['input_bundle_sha256'] == payload['input_bundle_sha256']
    assert observed['methods'] == payload['methods'] and observed['manuscript_eligible']
    assert observed['submission_eligible'] is False
    assert all(item['metadata']['submission_eligible'] is False for item in observed['figures'])
    assert load_planned_simulation_binding(tmp_path, hashlib.sha256(manifest.read_bytes()).hexdigest(), figures)


def test_existing_paper_projection_is_authenticated_and_rebound(tmp_path, monkeypatch):
    import hashlib
    from server.tests.test_simulation_table_publication import _current
    from server.services.simulation_table_publication import prepare_simulation_table_publication
    from server.services.simulation_table_projection_binding import verify_simulation_table_projection, PUBLICATION_BINDING
    manifest = _current(tmp_path, monkeypatch)
    update = prepare_simulation_table_publication(tmp_path, 'objective_mechanism')
    for relative, raw in update.files.items():
        (tmp_path / relative).write_bytes(raw)
    original_table = (tmp_path / 'paper/tables/synthetic_preview_results.tex').read_bytes()
    proof = verify_simulation_table_projection(tmp_path, json.loads(manifest.read_bytes()))
    assert proof
    result = correct_simulation_presentation(tmp_path)
    updated = verify_simulation_table_projection(tmp_path, json.loads(manifest.read_bytes()))
    assert updated['simulation_manifest_sha256'] == hashlib.sha256(manifest.read_bytes()).hexdigest()
    assert updated['source_table_text'] == proof['source_table_text']
    assert updated['source_hashes'] == proof['source_hashes']
    assert (tmp_path / 'paper/tables/synthetic_preview_results.tex').read_bytes() == original_table
    assert PUBLICATION_BINDING in result['changed_paths']


def test_foreign_table_projection_prevents_metadata_correction(tmp_path, monkeypatch):
    from server.tests.test_simulation_table_publication import _current
    from server.services.simulation_table_publication import prepare_simulation_table_publication
    from server.services.simulation_table_projection_binding import PUBLICATION_BINDING
    _current(tmp_path, monkeypatch)
    update = prepare_simulation_table_publication(tmp_path, 'objective_mechanism')
    for relative, raw in update.files.items():
        (tmp_path / relative).write_bytes(raw)
    proof_path = tmp_path / PUBLICATION_BINDING
    proof = json.loads(proof_path.read_bytes())
    proof['simulation_manifest_sha256'] = 'forged'
    proof_path.write_text(json.dumps(proof))
    before = _files(tmp_path)
    with pytest.raises(ValueError, match='binding is missing, stale or foreign'):
        correct_simulation_presentation(tmp_path)
    assert _files(tmp_path) == before
