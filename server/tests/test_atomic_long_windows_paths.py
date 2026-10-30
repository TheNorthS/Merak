"""Long Windows transaction paths preserve canonical artifact names and bytes."""

from pathlib import Path

from server.utils.atomic_write import atomic_replace_file, atomic_write_bytes, atomic_write_text


def _nested(root: Path) -> Path:
    return root / "source-bound-transaction" / "selected-scientific-evidence" / "experiments/results/simulated/reproducibility"


def test_atomic_sibling_suffix_does_not_break_windows_max_path_boundary(tmp_path):
    target = _nested(tmp_path) / "scenario_parameters.json"
    atomic_write_text(target, '{"registered":"current"}')
    atomic_write_bytes(target, b'{"registered":"revalidated"}')
    assert target.read_bytes() == b'{"registered":"revalidated"}'
    assert list(target.parent.glob("*.tmp")) == []
    assert "\\\\?\\" not in str(target)


def test_long_path_replace_keeps_source_owned_canonical_target(tmp_path):
    source = _nested(tmp_path) / "incoming-result.bin"
    target = source.with_name("canonical-result.bin")
    atomic_write_bytes(source, b"exact source-bound bytes")
    atomic_replace_file(source, target)
    assert not source.exists() and target.read_bytes() == b"exact source-bound bytes"
