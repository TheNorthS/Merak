"""Verify the source configuration facts supplied to architecture planning."""

from pathlib import Path

import pytest

from server.services.scientific_architecture_projection import _model_configuration


def _write_config(root: Path, source: str) -> None:
    path = root / "experiments" / "configs" / "main.yaml"
    path.parent.mkdir(parents=True)
    path.write_text(source, encoding="utf-8")


def test_top_level_configuration_preserves_disabled_probe_facts(tmp_path: Path) -> None:
    _write_config(tmp_path, """
model:
  backbone: shared_encoder
  subject_classes: null
  session_classes: null
  enable_leakage_audit: true
objective:
  subject_probe_weight: 0.0
  session_probe_weight: 0.0
data:
  require_subject_isolation: true
ablations:
  subject_session_probe: {enabled: true}
""")

    configuration = _model_configuration(tmp_path)

    assert configuration == {
        "backbone": "shared_encoder",
        "subject_classes": None,
        "session_classes": None,
        "enable_leakage_audit": True,
        "model_suite": [],
        "calibration": {},
        "objective": {"subject_probe_weight": 0.0, "session_probe_weight": 0.0},
        "data": {"require_subject_isolation": True},
        "ablations": {"subject_session_probe": {"enabled": True}},
    }


def test_method_configuration_keeps_existing_model_field_contract(tmp_path: Path) -> None:
    _write_config(tmp_path, """
method:
  model: {backbone: residual, embed_dim: 192}
  model_suite: [linear, residual]
  calibration: {fit_split: validation}
""")

    assert _model_configuration(tmp_path) == {
        "backbone": "residual",
        "embed_dim": 192,
        "model_suite": ["linear", "residual"],
        "calibration": {"fit_split": "validation"},
    }


def test_explicit_top_level_sections_override_nested_configuration(tmp_path: Path) -> None:
    _write_config(tmp_path, """
method:
  model: {subject_classes: 12}
  model_suite: [legacy]
  objective: {subject_probe_weight: 1.0}
  data: {require_subject_isolation: true}
  ablations: {subject_session_probe: {enabled: true}}
model: {subject_classes: null}
model_suite: []
objective: {subject_probe_weight: 0.0}
data: {}
ablations: null
""")

    assert _model_configuration(tmp_path) == {
        "subject_classes": None,
        "model_suite": [],
        "calibration": {},
        "objective": {"subject_probe_weight": 0.0},
        "data": {},
    }


@pytest.mark.parametrize("source", ["model: [", "- not a mapping", "null"])
def test_unparseable_configuration_has_no_inferred_model_facts(
    tmp_path: Path, source: str,
) -> None:
    _write_config(tmp_path, source)

    assert _model_configuration(tmp_path) == {}


def test_invalid_section_types_do_not_become_model_facts(tmp_path: Path) -> None:
    _write_config(tmp_path, """
method: absent
model: [not, a, model]
model_suite: not_a_suite
calibration: [invalid]
objective: disabled
data: null
ablations: []
""")

    assert _model_configuration(tmp_path) == {"model_suite": [], "calibration": {}}
