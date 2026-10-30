"""Pure producer-to-plan regression coverage; no figures or simulations run."""

from pathlib import Path
import hashlib
import json

import pytest

from server.services import simulation_render_specs
from server.services.artifact_contract import artifact_write_error
from server.services.figure_spec_repository import persist_figure_specs
from server.services.figure_routing import recommend_figure_route
from server.services.risk_stage_figure import _rule_2
from server.services.publication_figure_labels import validate_publication_labels
from server.services.scientific_simulation_assets import _simulation_asset
from server.services.simulation_manifest_validation import figure_issues
from server.services.simulation_policy import SIMULATION_STABLE_IDS, SIMULATION_PLOT_FAMILIES
from server.workflows.revision_targets import revision_asset_ids
from server.services.simulation_publication_registry import register_simulation_figures


@pytest.mark.parametrize('domain', ['eeg', 'vision', 'clinical', 'formal', 'qualitative'])
def test_all_render_spec_producers_declare_current_labels(monkeypatch, tmp_path, domain):
    builders = ['_main', '_sensitivity', '_progression', '_robustness',
                '_case_analysis', '_coverage', '_burden']
    ids = list(SIMULATION_STABLE_IDS.values())
    for builder, asset_id in zip(builders, ids, strict=True):
        monkeypatch.setattr(
            simulation_render_specs, builder,
            lambda *_args, semantic_id=asset_id: {'id': semantic_id},
        )
    specs = simulation_render_specs.build_render_specs(
        None, assets={}, asset_profile={'specialized_domain': domain},
        data_paths={}, simulated_figures=tmp_path, claim_ids=['C1'],
        primary_metric='balanced_accuracy', primary_metric_axis_label='Balanced accuracy',
        metric_direction='maximize', publication_style={}, progression_axis='hours',
        axis='noise', slice_field='group', slice_metric_axis_label='Error rate',
        validation_curve_labels=('Coverage', 'Risk'), coverage_y_axis_label='Selective risk',
        simulated_ablation=[], simulated_efficiency=[], use_eeg_shift_renderer=False,
    )
    assert len(specs) == 7
    for spec in specs:
        assert spec['producer_kind'] == 'deterministic'
        assert validate_publication_labels(spec['publication_labels'])[1] == []


def test_simulation_plan_preserves_producer_and_labels(tmp_path: Path):
    labels = [{'schema': 1, 'id': 'main.metric', 'kind': 'metric',
               'display_text': 'Balanced accuracy'}]
    record = {'id': 'synthetic_preview_main_comparison',
              'producer_kind': 'deterministic', 'publication_labels': labels,
              'source': 'figures/simulated/simulated_main_comparison.py',
              'outputs': {'pdf': 'figures/simulated/simulated_main_comparison.pdf'}}
    asset = _simulation_asset(
        tmp_path, tmp_path / 'experiments/results/simulated/SIMULATION_MANIFEST.json',
        record, {'data_file': 'main_comparison.csv'}, ['C1'],
    )
    assert asset['producer_kind'] == 'deterministic'
    assert asset['publication_labels'] == labels
    assert asset['source_path'] == record['source']
    assert asset['generation_policy'] == 'reuse'


def test_simulation_manifest_rejects_contract_gap_before_figure_node():
    records = [{'id': identity, 'plot_family': SIMULATION_PLOT_FAMILIES[role]}
               for role, identity in SIMULATION_STABLE_IDS.items()]
    issues, _ = figure_issues(
        {'figure_files': records}, ids=SIMULATION_STABLE_IDS,
        plot_families=SIMULATION_PLOT_FAMILIES,
    )
    assert any('deterministic producer' in issue for issue in issues)
    assert any('publication_labels' in issue for issue in issues)


def test_missing_method_asset_is_retained_in_structured_repair_scope():
    findings = []
    _rule_2('', {'assets': [{'id': 'method_architecture', 'kind': 'figure'}]},
            [], findings, {'run_experiment': False})
    assert findings[0]['asset_ids'] == ['method_architecture']
    assert revision_asset_ids(findings) == ['method_architecture']


def test_spec_repository_keeps_complete_assets_and_rejects_invalid_replacement(tmp_path):
    labels = [{'schema': 1, 'id': 'score.metric', 'kind': 'metric',
               'display_text': 'Balanced accuracy'}]
    plan = {'assets': [
        {'id': 'method_architecture', 'kind': 'figure', 'producer_kind': 'model',
         'publication_labels': labels},
        {'id': 'synthetic_preview_main_comparison', 'kind': 'figure',
         'producer_kind': 'deterministic', 'publication_labels': labels},
    ]}
    persisted = persist_figure_specs(tmp_path, plan)
    path = tmp_path / 'figures/FIGURE_SPECS.json'
    original = path.read_bytes()
    payload = json.loads(original)
    assert payload['schema'] == 4
    assert payload['publication_label_schema'] == 1
    assert [item['id'] for item in persisted] == [item['id'] for item in plan['assets']]
    assert 'runtime-owned' in artifact_write_error(tmp_path, path)
    plan['assets'][0].pop('publication_labels')
    with pytest.raises(ValueError, match='publication_labels'):
        persist_figure_specs(tmp_path, plan)
    assert path.read_bytes() == original


def test_spec_repository_persists_and_validates_figure_nature_policy(tmp_path):
    labels = [{
        'schema': 1, 'id': 'method.term', 'kind': 'concept',
        'display_text': 'Shared encoder',
    }]
    route = recommend_figure_route({
        'id': 'method_architecture', 'kind': 'figure',
        'scientific_role': 'method', 'figure_nature': 'conceptual',
    })
    asset = {
        'id': 'method_architecture', 'kind': 'figure',
        'publication_labels': labels, **route,
    }

    persisted = persist_figure_specs(tmp_path, {'assets': [asset]})
    payload = json.loads((tmp_path / 'figures/FIGURE_SPECS.json').read_text())

    assert payload['production_policy_schema'] == 1
    assert payload['generator_policy'] == 'figure-nature-routing-v2'
    assert persisted[0]['production_strategy'] == 'deterministic_architecture'
    assert persisted[0]['recommended_skill'] == 'figure-spec'

    asset['composition_owner'] = 'model'
    with pytest.raises(ValueError, match='composition_owner=runtime'):
        persist_figure_specs(tmp_path, {'assets': [asset]})


def test_explicit_full_svg_route_survives_spec_persistence(tmp_path):
    route = recommend_figure_route({
        'id': 'method_architecture', 'kind': 'figure',
        'figure_nature': 'conceptual',
        'production_strategy': 'model_composed_full_svg',
    })
    asset = {
        'id': 'method_architecture', 'kind': 'figure',
        'publication_labels': [{
            'schema': 1, 'id': 'method.term', 'kind': 'concept',
            'display_text': 'Shared encoder',
        }],
        **route,
    }

    persisted = persist_figure_specs(tmp_path, {'assets': [asset]})

    assert persisted[0]['production_strategy'] == 'model_composed_full_svg'
    assert persisted[0]['recommended_backend'] == 'rich_svg'
    assert persisted[0]['producer_kind'] == 'model'
    asset['recommended_backend'] = 'figurespec'
    with pytest.raises(ValueError, match='recommended_backend=rich_svg'):
        persist_figure_specs(tmp_path, {'assets': [asset]})


def test_simulation_registration_retains_typed_owner_metadata(tmp_path, monkeypatch):
    from server.services.figure_artifacts import figure_artifact_registry
    from server.tests._scientific_slide_fixture import write_current_slide_bundle

    paths = write_current_slide_bundle(tmp_path)
    manifest_path = paths['simulation_manifest']
    simulation = json.loads(manifest_path.read_text(encoding='utf-8'))
    profiles = {item['semantic_id']: item for item in simulation['domain_asset_profile']}
    rendered = []
    for record in simulation['figure_files']:
        profile = profiles[record['id']]
        rendered.append({**record, 'description': 'Declared finite comparison with uncertainty',
                         'role': profile['stable_role'], 'domain_asset_role': profile['domain_role'],
                         'scientific_question': 'How do the declared finite conditions compare?',
                         'label': profile['label'], 'intended_comparison': 'Reference and declared condition',
                         'visual_encoding': 'Comparison with intervals', 'uncertainty_encoding': 'Declared interval',
                         'claim_ids': ['C1'], 'script': tmp_path / record['source'],
                         'data': tmp_path / 'experiments/results/simulated' / profile['data_file'],
                         'outputs': {kind: tmp_path / value for kind, value in record['outputs'].items()}})
    captured = []

    def record(**kwargs):
        captured.append(kwargs['metadata'])
        return Path('manifest'), {'id': 'main'}

    monkeypatch.setattr(figure_artifact_registry, 'record', record)
    register_simulation_figures(
        tmp_path, rendered, {}, simulation['simulation_id'], '1729', 'fixture',
        manifest_path, hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
    )
    assert len(captured) == 7
    for metadata, item in zip(captured, rendered, strict=True):
        assert metadata['producer_kind'] == 'deterministic'
        assert metadata['publication_labels'] == item['publication_labels']
    assert {item['semantic_key'] for item in captured if item['paper_selected']} == {
        'synthetic_preview_main_comparison', 'synthetic_preview_ablation',
        'synthetic_preview_robustness', 'synthetic_preview_calibration',
    }
