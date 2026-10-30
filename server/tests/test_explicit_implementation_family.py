"""Background comparisons must not override the user's selected research discipline."""

import pytest

from server.services.implementation_blueprint import infer_family
from server.services.publication_style import publication_style_service


@pytest.mark.parametrize('background', [
    'Compare a linear predictor with persistence. No neural networks or transformer training.',
    'The literature discusses deep learning and contrastive embedding; only CPU numerical estimation is authorized.',
])
def test_explicit_engineering_simulation_stays_computational(background):
    profile = publication_style_service.build(context=background,
        research_family='engineering_systems', study_archetype='simulation_modeling')
    assert profile['implementation_family'] == 'computational_general'
    assert infer_family({'background': background}, profile) == 'computational_general'


@pytest.mark.parametrize('family', ['computational_general', 'external_protocol', 'formal_verification', 'machine_learning'])
def test_declared_implementation_family_precedes_incidental_keywords(family):
    assert infer_family({'notes': 'neural classifier accuracy theorem observational'},
                        {'implementation_family': family}) == family


def test_auto_and_explicit_ml_still_use_neural_implementation():
    profile = publication_style_service.build(context='Train a transformer classifier with ablations')
    assert profile['implementation_family'] == 'machine_learning'
    explicit = publication_style_service.build(context='Numerical simulation', research_family='machine_learning')
    assert explicit['implementation_family'] == 'machine_learning'


def test_computational_audit_does_not_demand_neural_optimizer_from_background_text(tmp_path):
    import json
    from server.services.experiment_implementation import experiment_implementation_service
    directory = tmp_path / 'experiments/src'
    directory.mkdir(parents=True)
    (directory / 'run_analysis.py').write_text('''import json
def main():
    results = [value * value for value in range(3)]
    with open("metrics.json", "w") as output:
        json.dump(results, output)
if __name__ == "__main__":
    main()
''')
    method = {'status': 'implemented', 'implementation_level': 'executable_experiment_pipeline',
              'implementation_family': 'computational_general',
              'background': 'No neural encoder, classifier, AUROC or transformer training is performed.'}
    (tmp_path / 'experiments/METHOD_CONTRACT.json').write_text(json.dumps(method))
    (tmp_path / 'experiments/RUN_SPEC.json').write_text(json.dumps({
        'implementation_family': 'computational_general', 'entrypoint': 'experiments/src/run_analysis.py',
        'command': 'python experiments/src/run_analysis.py'}))
    report = experiment_implementation_service.audit(tmp_path)
    assert report['is_machine_learning'] is False
    assert not any(item['id'] == 'IMPL-FLOW-OPTIMIZATION' for item in report['findings'])
    assert not any('task head' in item['message'] for item in report['findings'])
    method['implementation_family'] = 'machine_learning'
    (tmp_path / 'experiments/METHOD_CONTRACT.json').write_text(json.dumps(method))
    report = experiment_implementation_service.audit(tmp_path)
    assert report['is_machine_learning'] is True
    assert any(item['id'] == 'IMPL-FLOW-OPTIMIZATION' for item in report['findings'])
