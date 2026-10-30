"""Pure real-snapshot compiler isolation without launching a process."""

from pathlib import Path

import pytest

from scripts.live_snapshot_compilation import guarded_compile_command


def test_current_latex_compiler_is_kept_but_external_rc_and_shell_are_disabled(tmp_path):
    paper = tmp_path / "paper"
    command = ["latexmk", "-pdf", "-halt-on-error", f"-outdir={paper}", str(paper / "main.tex")]
    checked, cwd = guarded_compile_command(tmp_path, command, str(paper))
    assert checked == ["latexmk", "-norc", "-no-shell-escape", *command[1:]]
    assert cwd == str(paper)


@pytest.mark.parametrize("command", [
    ["python", "train.py"], ["cmd", "/c", "latexmk"], ["latexmk", "-shell-escape"],
    ["latexmk", "-e", "custom code"], ["latexmk", "-r", "external.rc"],
])
def test_arbitrary_execution_and_shell_options_are_denied(tmp_path, command):
    with pytest.raises(ValueError):
        guarded_compile_command(tmp_path, command, str(tmp_path / "paper"))


def test_foreign_output_and_working_directory_are_denied(tmp_path):
    with pytest.raises(ValueError, match="artifact directory"):
        guarded_compile_command(tmp_path, ["latexmk", "main.tex"], str(tmp_path.parent))
    with pytest.raises(ValueError, match="leaves"):
        guarded_compile_command(tmp_path, ["latexmk", f"-outdir={tmp_path.parent}"], str(tmp_path / "paper"))


def test_pdfinfo_fallback_remains_bound_to_snapshot_pdf(tmp_path):
    pdf = tmp_path / "paper/main.pdf"
    checked, cwd = guarded_compile_command(tmp_path, ["pdfinfo", str(pdf)], None)
    assert checked == ["pdfinfo", str(pdf)] and cwd == str(pdf.parent)


@pytest.mark.parametrize("command", [
    ["latexmk", "-r=unsafe.rc", "main.tex"], ["latexmk", "-e=custom", "main.tex"],
    ["latexmk", "-pdflatex=python train.py", "main.tex"], ["latexmk", "../../outside.tex"],
    ["latexmk", "-outdir=../../foreign", "main.tex"], ["pdfinfo", "../../outside.pdf"],
])
def test_relative_escapes_and_custom_execution_flags_remain_blocked(tmp_path, command):
    with pytest.raises(ValueError):
        guarded_compile_command(tmp_path, command, str(tmp_path / "paper"))


def test_scientific_directories_and_root_outputs_are_never_compiler_write_targets(tmp_path):
    with pytest.raises(ValueError, match="artifact directory"):
        guarded_compile_command(tmp_path, ["latexmk", "main.tex"], str(tmp_path / "experiments"))
    for command in (["latexmk", f"-outdir={tmp_path}", "main.tex"],
                    ["latexmk", str(tmp_path / "experiments/scientific.tex")]):
        with pytest.raises(ValueError, match="leaves"):
            guarded_compile_command(tmp_path, command, str(tmp_path / "paper"))


def _trusted(root):
    from scripts.live_snapshot_compilation import _AUTHORIZED_SPAWN
    executable = root.parent / "trusted-tools/latexmk.exe"
    work = root / "paper"
    command = [str(executable), "-norc", "-no-shell-escape", "-pdf", str(work / "main.tex")]
    return command, str(work), _AUTHORIZED_SPAWN.set((tuple(command), str(work)))


def test_windows_none_executable_matches_only_exact_trusted_list2cmdline(tmp_path):
    import subprocess
    from scripts.live_snapshot_compilation import _AUTHORIZED_SPAWN, validate_spawn_scope
    command, cwd, token = _trusted(tmp_path)
    try:
        validate_spawn_scope(tmp_path, None, subprocess.list2cmdline(command), cwd)
        validate_spawn_scope(tmp_path, command[0], command, cwd)
    finally:
        _AUTHORIZED_SPAWN.reset(token)


@pytest.mark.parametrize("defect", ["no-context", "command-string", "interpreter", "cwd", "explicit-executable", "flags"])
def test_process_audit_refuses_untrusted_or_changed_calls(tmp_path, defect):
    import subprocess
    from scripts.live_snapshot_compilation import _AUTHORIZED_SPAWN, validate_spawn_scope
    command, cwd, token = _trusted(tmp_path)
    executable = None
    try:
        if defect == "no-context":
            _AUTHORIZED_SPAWN.set(None)
        elif defect == "command-string":
            command = ["cmd.exe", "/c", "latexmk main.tex"]
        elif defect == "interpreter":
            command = ["perl.exe", "arbitrary.pl"]
        elif defect == "cwd":
            cwd = str(tmp_path.parent)
        elif defect == "explicit-executable":
            executable = str(tmp_path.parent / "foreign/latexmk.exe")
        else:
            command.append("-shell-escape")
        with pytest.raises((PermissionError, ValueError)):
            validate_spawn_scope(tmp_path, executable, subprocess.list2cmdline(command), cwd)
    finally:
        _AUTHORIZED_SPAWN.reset(token)


@pytest.mark.asyncio
async def test_trusted_scope_propagates_to_compiler_worker_thread_and_resets(tmp_path, monkeypatch):
    import asyncio
    import subprocess
    from scripts import live_snapshot_compilation as service
    from server.services.paper_compiler import paper_compiler

    executable = tmp_path.parent / "trusted-tools/latexmk.exe"
    observed = []

    async def fake_command(command, *, cwd=None, **_options):
        def worker():
            service.validate_spawn_scope(tmp_path, None, subprocess.list2cmdline(command), cwd)
            observed.append(command)
        await asyncio.to_thread(worker)
        return "local compiler fixture result"

    monkeypatch.setattr(service.shutil, "which", lambda _name: str(executable))
    monkeypatch.setattr(paper_compiler, "_run_command", fake_command)
    with service.restricted_snapshot_compilation(tmp_path):
        assert await paper_compiler._run_command(["latexmk", "main.tex"], cwd=str(tmp_path / "paper"), timeout=1) == "local compiler fixture result"
    assert observed[0][0] == str(executable.resolve())
    with pytest.raises(PermissionError, match="lacks an authorized"):
        service.validate_spawn_scope(tmp_path, None, subprocess.list2cmdline(observed[0]), str(tmp_path / "paper"))


@pytest.mark.asyncio
async def test_project_owned_same_name_compiler_and_foreign_explicit_path_are_rejected(tmp_path, monkeypatch):
    from scripts import live_snapshot_compilation as service
    from server.services.paper_compiler import paper_compiler

    monkeypatch.setattr(service.shutil, "which", lambda _name: str(tmp_path / "paper/latexmk.exe"))
    with service.restricted_snapshot_compilation(tmp_path):
        with pytest.raises(ValueError, match="project-owned"):
            await paper_compiler._run_command(["latexmk", "main.tex"], cwd=str(tmp_path / "paper"), timeout=1)
    monkeypatch.setattr(service.shutil, "which", lambda _name: str(tmp_path.parent / "trusted/latexmk.exe"))
    with service.restricted_snapshot_compilation(tmp_path):
        with pytest.raises(ValueError, match="differs from"):
            await paper_compiler._run_command([str(tmp_path.parent / "foreign/latexmk.exe"), "main.tex"], cwd=str(tmp_path / "paper"), timeout=1)
