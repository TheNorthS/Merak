"""Frozen validators use the packaged source mirror, not cwd or a system Python."""

from pathlib import Path

import pytest

from server.utils import runtime_source_root as source


def test_development_source_root_is_independent_of_current_directory(tmp_path, monkeypatch):
    monkeypatch.setattr(source.sys, "frozen", False, raising=False)
    monkeypatch.chdir(tmp_path)
    expected = Path(source.__file__).resolve().parents[1]
    assert source.server_source_root() == expected
    assert source.implementation_source_path(expected / "services/paper_section_review.py") == (
        expected / "services/paper_section_review.py"
    )


def test_frozen_backend_uses_its_canonical_source_mirror(tmp_path, monkeypatch):
    mirror = tmp_path / "merak-source/server"
    mirror.mkdir(parents=True)
    monkeypatch.setattr(source.sys, "frozen", True, raising=False)
    monkeypatch.setattr(source.sys, "_MEIPASS", str(tmp_path), raising=False)
    assert source.server_source_root() == mirror


@pytest.mark.parametrize("resource", [None, "", 42])
def test_frozen_backend_without_resource_root_fails_closed(resource, monkeypatch):
    monkeypatch.setattr(source.sys, "frozen", True, raising=False)
    monkeypatch.setattr(source.sys, "_MEIPASS", resource, raising=False)
    with pytest.raises(RuntimeError, match="bundle resource root"):
        source.server_source_root()


def test_frozen_missing_mirror_does_not_fall_back_to_development_files(tmp_path, monkeypatch):
    monkeypatch.setattr(source.sys, "frozen", True, raising=False)
    monkeypatch.setattr(source.sys, "_MEIPASS", str(tmp_path), raising=False)
    with pytest.raises(RuntimeError, match="source mirror is missing"):
        source.server_source_root()


def test_frozen_implementation_path_maps_only_owned_server_files(tmp_path, monkeypatch):
    loaded = tmp_path / "server"
    mirror = tmp_path / "merak-source/server"
    mirror.mkdir(parents=True)
    monkeypatch.setattr(source, "__file__", str(loaded / "utils/runtime_source_root.py"))
    monkeypatch.setattr(source.sys, "frozen", True, raising=False)
    monkeypatch.setattr(source.sys, "_MEIPASS", str(tmp_path), raising=False)
    assert source.implementation_source_path(loaded / "workflows/engine_inputs.py") == (
        mirror / "workflows/engine_inputs.py"
    )
    skill = tmp_path / "merak-skills/paper-write/SKILL.md"
    assert source.implementation_source_path(skill) == skill


def test_frozen_risk_sources_are_enumerated_from_mirror_not_pyc_directory(tmp_path, monkeypatch):
    from server.services.risk_validator_sources import risk_validator_source_paths

    mirror = tmp_path / "merak-source/server"
    services = mirror / "services"
    services.mkdir(parents=True)
    split_validator = services / "risk_stage_ppt.py"
    split_validator.write_text("# packaged risk validator", encoding="utf-8")
    loaded = tmp_path / "server"
    monkeypatch.setattr(source, "__file__", str(loaded / "utils/runtime_source_root.py"))
    monkeypatch.setattr(source.sys, "frozen", True, raising=False)
    monkeypatch.setattr(source.sys, "_MEIPASS", str(tmp_path), raising=False)
    paths = risk_validator_source_paths(loaded / "services")
    assert split_validator in paths
    native = {tmp_path / "merak-skills/figure-spec/scripts" / name
              for name in ("figure_renderer.py", "figure_semantic_rendering.py")}
    assert native.issubset(paths)
    assert all(path.is_relative_to(mirror) or path in native for path in paths)
