"""Pure checks that bundled simulation provenance uses real source bytes."""

from __future__ import annotations

from pathlib import Path

import pytest

from server.services import simulation_reproducibility as reproducibility


def test_frozen_generator_uses_packaged_source_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = tmp_path / "bundle"
    source = bundle / "merak-source/server/services/simulation_benchmark.py"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"# exact generator source\r\n")
    frozen_module = bundle / "server/services/simulation_reproducibility.py"
    verifier = frozen_module.parent / "simulation_plot_templates/verify_bundle.py.tmpl"
    verifier.parent.mkdir(parents=True)
    verifier.write_text("# verifier\n", encoding="utf-8")
    monkeypatch.setattr(reproducibility, "__file__", str(frozen_module))
    monkeypatch.setattr(reproducibility.sys, "frozen", True, raising=False)
    monkeypatch.setattr(reproducibility.sys, "_MEIPASS", str(bundle), raising=False)

    expected_module = frozen_module.with_name("simulation_benchmark.py")
    assert reproducibility._generator_source_path(expected_module) == source
    output = reproducibility.materialize_reproducibility_bundle(
        tmp_path / "project", tmp_path / "project/results/simulated",
        generator_source=expected_module, simulation_id="sim-1",
        simulation_seed="7", seed_ids=[7], method_records=[],
        registered_axes=[], holm_family_size=0, holm_alpha=0.05,
    )
    assert output["generator_source.py"].read_bytes() == source.read_bytes()

    source.unlink()
    with pytest.raises(RuntimeError, match="source snapshot is unavailable"):
        reproducibility._generator_source_path(expected_module)


def test_frozen_generator_preserves_explicit_source_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "custom_generator.py"
    source.write_text("# custom source\n", encoding="utf-8")
    monkeypatch.setattr(reproducibility.sys, "frozen", True, raising=False)
    monkeypatch.setattr(reproducibility.sys, "_MEIPASS", str(tmp_path), raising=False)
    assert reproducibility._generator_source_path(source) == source
