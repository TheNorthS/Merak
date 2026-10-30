"""Equivalent extended Windows paths remain inside the exact offline boundary."""

import os

import pytest

from scripts.verify_offline_suite import _write_path, canonical_io_path


@pytest.mark.skipif(os.name != "nt", reason="Windows extended path spelling")
def test_extended_local_path_has_the_same_owned_boundary(tmp_path):
    target = tmp_path / "deep/evidence.json"
    extended = "\\\\?\\" + str(target)
    assert canonical_io_path(extended) == target.resolve()
    _write_path(extended, tmp_path)


@pytest.mark.skipif(os.name != "nt", reason="Windows extended path spelling")
def test_extended_foreign_path_still_fails_closed(tmp_path):
    target = tmp_path.parent / "foreign-evidence.json"
    with pytest.raises(PermissionError, match="shared path"):
        _write_path("\\\\?\\" + str(target), tmp_path)


def test_normal_foreign_path_cannot_be_written(tmp_path):
    with pytest.raises(PermissionError):
        _write_path(tmp_path.parent / "foreign-evidence.json", tmp_path)
