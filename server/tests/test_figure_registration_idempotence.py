"""No-op registration preserves review snapshots; real artifact changes still invalidate them."""
import hashlib

import pytest

from server.services.figure_artifacts import figure_artifact_registry as registry


def fixture(tmp_path):
    output = tmp_path / "figures/local.pdf"
    output.parent.mkdir()
    output.write_bytes(b"fixture-pdf-identity")
    source = output.with_suffix(".py")
    source.write_text("VALUES = [1, 2]\n")
    return dict(output_dir=output.parent, figure_type="matplotlib", description="Source comparison",
        output_path=str(output), source_path=str(source),
        metadata={"semantic_key": "comparison", "scientific_role": "result", "caption": "Source comparison"})


def test_identical_registration_preserves_manifest_bytes_mtime_and_entry(tmp_path, monkeypatch):
    args = fixture(tmp_path)
    manifest, first = registry.record(**args)
    markdown = manifest.with_suffix(".md")
    before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in (manifest, markdown)}
    import server.services.figure_manifest_repository as repository
    monkeypatch.setattr(repository.time, "time", lambda: first["created_at"] + 600)
    monkeypatch.setattr(repository, "atomic_write_json", lambda *a, **k: pytest.fail("No-op must not write"))
    for _ in range(3):
        path, entry = registry.record(**args)
        assert path == manifest and entry == first
    assert {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in before} == before


@pytest.mark.parametrize("change", ["source", "output", "caption"])
def test_actual_content_change_invalidates_manifest_hash(tmp_path, change):
    from pathlib import Path
    args = fixture(tmp_path)
    manifest, first = registry.record(**args)
    before = hashlib.sha256(manifest.read_bytes()).hexdigest()
    if change == "caption":
        args["metadata"]["caption"] = "Revised scientific comparison"
    else:
        Path(args[change + "_path"]).write_bytes(b"changed-content")
    _, entry = registry.record(**args)
    assert hashlib.sha256(manifest.read_bytes()).hexdigest() != before
    assert entry != first
