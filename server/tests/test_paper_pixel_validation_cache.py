"""Scoped reuse cannot hide re-signed pixels, changed scientific inputs or failed proofs."""

import pytest

from server.services.paper_pixel_validation_cache import pixel_validation_scope, validate_pixels_once


@pytest.fixture
def proof(tmp_path):
    files = ['input.csv', 'plot.py', 'derived.py', 'plot.pdf', 'plot.svg', 'plot.png']
    for name in files:
        (tmp_path / name).write_text(name)
    packet = {'original_inputs_sha256': {'input.csv': 'a', 'plot.py': 'b'},
        'source': 'plot.py', 'source_path': 'derived.py',
        'derived_paths': dict(zip(['source', 'pdf', 'svg', 'png'], files[2:]))}
    return tmp_path, packet


def test_identical_proof_reused_only_within_current_gate(proof):
    root, packet = proof
    calls = []
    def validate():
        calls.append(1)
        return []
    for _ in range(2):
        with pixel_validation_scope():
            assert validate_pixels_once(root, packet, validate) == []
            assert validate_pixels_once(root, packet, validate) == []
    assert len(calls) == 2
    validate_pixels_once(root, packet, validate)
    validate_pixels_once(root, packet, validate)
    assert len(calls) == 4


@pytest.mark.parametrize('name', ['input.csv', 'plot.py', 'derived.py', 'plot.pdf', 'plot.svg', 'plot.png'])
def test_changed_bytes_force_fresh_proof_even_with_resigned_packet(proof, name):
    root, packet = proof
    calls = []
    def validate():
        calls.append(1)
        return [] if len(calls) == 1 else ['pixels changed']
    with pixel_validation_scope():
        assert not validate_pixels_once(root, packet, validate)
        (root / name).write_text('forged')
        packet['new_self_signed_hash'] = 'forged'
        assert validate_pixels_once(root, packet, validate) == ['pixels changed']
    assert len(calls) == 2


def test_failures_and_mutations_during_validation_are_never_cached(proof):
    root, packet = proof
    calls = []
    def validate():
        calls.append(1)
        return ['invalid']
    with pixel_validation_scope():
        assert validate_pixels_once(root, packet, validate)
        assert validate_pixels_once(root, packet, validate)
    assert len(calls) == 2
    def mutate():
        calls.append(1)
        (root / 'input.csv').write_text(str(len(calls)))
        return []
    with pixel_validation_scope():
        assert validate_pixels_once(root, packet, mutate) == ['Paper pixel proof inputs changed during validation']
        assert validate_pixels_once(root, packet, mutate) == ['Paper pixel proof inputs changed during validation']
    assert len(calls) == 4


def test_current_renderer_change_invalidates_proof(proof, monkeypatch):
    from server.services import paper_derived_figure_rendering as rendering
    root, packet = proof
    calls = []
    def validate():
        calls.append(1)
        return []
    with pixel_validation_scope():
        validate_pixels_once(root, packet, validate)
        monkeypatch.setattr(rendering, '_renderer_digest', lambda: 'changed')
        validate_pixels_once(root, packet, validate)
    assert len(calls) == 2


def test_nested_gate_is_isolated_and_exception_discards_cache(proof):
    root, packet = proof
    calls = []
    def validate():
        calls.append(1)
        return []
    with pytest.raises(RuntimeError), pixel_validation_scope():
        validate_pixels_once(root, packet, validate)
        with pixel_validation_scope():
            validate_pixels_once(root, packet, validate)
        raise RuntimeError('cancelled')
    validate_pixels_once(root, packet, validate)
    assert len(calls) == 3
