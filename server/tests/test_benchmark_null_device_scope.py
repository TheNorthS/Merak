"""Windows compiler null input is a device, not a foreign scientific file."""

import os
from pathlib import Path

import pytest

from scripts.full_benchmark_scope import write_is_allowed


@pytest.mark.skipif(os.name != "nt", reason="Exact Windows null-device spelling")
@pytest.mark.parametrize("device", ["nul", "NUL", b"nul", Path("nul"), r"\\.\NUL", r"\\?\nul"])
def test_only_explicit_null_devices_are_allowed_for_noninteractive_compilation(tmp_path, device):
    assert write_is_allowed(tmp_path, device, rerun_literature=False)


@pytest.mark.parametrize("relative", ["nul.txt", "temporary-output.log", "experiments/results/simulated/data.csv",
    "experiments/src/train.py", "ideas/SELECTED_IDEA.json"])
def test_null_device_support_does_not_authorize_new_root_or_frozen_files(tmp_path, relative):
    assert not write_is_allowed(tmp_path, tmp_path / relative, rerun_literature=False)


@pytest.mark.parametrize("relative", ["foreign.txt", "nul.txt", "nested/nul"])
def test_same_name_or_nested_foreign_paths_do_not_acquire_device_permission(tmp_path, relative):
    root = tmp_path / "authorized-copy"
    assert not write_is_allowed(root, tmp_path / "other-project" / relative, rerun_literature=False)
