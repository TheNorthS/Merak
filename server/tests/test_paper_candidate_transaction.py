"""Exercise actual file tools and validation views against isolated durable candidates."""

import asyncio
import json

import pytest

from server.agent.tools.file_tools import file_edit, file_read, file_write
from server.services.manuscript_text import read_text, sha256
from server.services.paper_candidate_transaction import PaperCandidate


def setup(root, name='03_method.tex'):
    target = root / 'paper/sections' / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text('Verified formula.\n\nUnrelated accepted paragraph.\n')
    return target


@pytest.mark.asyncio
async def test_read_write_and_validator_see_candidate_while_original_is_untouched(tmp_path):
    target = setup(tmp_path)
    original, digest = target.read_bytes(), sha256(target)
    candidate = PaperCandidate(tmp_path, 'method', [target], lambda: 'inputs')
    with candidate:
        await file_edit(str(target), 'Verified formula.', 'Corrected formula.')
        assert 'Corrected' in await file_read(str(target))
        assert 'Corrected' in read_text(target)
        assert sha256(target) != digest
        assert target.read_bytes() == original
    assert target.read_bytes() == original
    candidate.publish({'passed': True, 'issues': []})
    assert 'Corrected' in target.read_text()
    assert json.loads(candidate.receipt.read_bytes())['status'] == 'committed'


@pytest.mark.asyncio
async def test_rejected_or_cancelled_candidate_survives_for_resume_but_never_changes_original(tmp_path):
    target = setup(tmp_path)
    original = target.read_bytes()
    candidate = PaperCandidate(tmp_path, 'method', [target], lambda: 'inputs')
    with pytest.raises(asyncio.CancelledError):
        with candidate:
            await file_edit(str(target), 'Verified formula.', 'Partial candidate.')
            raise asyncio.CancelledError()
    assert target.read_bytes() == original
    resumed = PaperCandidate(tmp_path, 'method', [target], lambda: 'inputs')
    with resumed:
        assert 'Partial candidate' in read_text(target)
    resumed.publish({'passed': False, 'issues': ['scientific mismatch']})
    assert target.read_bytes() == original


@pytest.mark.asyncio
@pytest.mark.parametrize('changed', ['input', 'canonical'])
async def test_stale_candidate_cannot_overwrite_new_inputs_or_user_edit(tmp_path, changed):
    target = setup(tmp_path)
    inputs = ['old']
    candidate = PaperCandidate(tmp_path, 'method', [target], lambda: inputs[0])
    with candidate:
        await file_edit(str(target), 'Verified formula.', 'Candidate formula.')
    if changed == 'input':
        inputs[0] = 'new'
    else:
        target.write_text('User edit')
    original = target.read_bytes()
    with pytest.raises(ValueError, match='changed'):
        candidate.publish({'passed': True})
    assert target.read_bytes() == original


@pytest.mark.asyncio
async def test_existing_whole_file_write_and_foreign_mutation_are_blocked(tmp_path):
    target = setup(tmp_path)
    foreign = setup(tmp_path, '04_experiments.tex')
    with PaperCandidate(tmp_path, 'method', [target], lambda: 'inputs'):
        with pytest.raises(PermissionError, match='focused Edit'):
            await file_write(str(target), 'replace whole chapter')
        with pytest.raises(PermissionError, match='exact current-stage'):
            await file_edit(str(foreign), 'Verified formula.', 'Foreign change')
    assert 'Foreign' not in foreign.read_text()


@pytest.mark.asyncio
async def test_new_target_is_created_only_after_validation(tmp_path):
    target = tmp_path / 'paper/sections/01_introduction.tex'
    with PaperCandidate(tmp_path, 'introduction', [target], lambda: 'inputs') as candidate:
        await file_write(str(target), 'Candidate introduction')
        assert not target.exists() and read_text(target) == 'Candidate introduction'
    candidate.publish({'passed': True})
    assert target.read_text() == 'Candidate introduction'


@pytest.mark.asyncio
async def test_interrupted_multifile_commit_restores_baselines_before_resuming(tmp_path):
    one, two = setup(tmp_path, 'a.tex'), setup(tmp_path, 'b.tex')
    original = one.read_bytes()
    candidate = PaperCandidate(tmp_path, 'front_matter', [one, two], lambda: 'inputs')
    with candidate:
        await file_edit(str(one), 'Verified formula.', 'First candidate.')
        await file_edit(str(two), 'Verified formula.', 'Second candidate.')
    candidate.record('committing')
    one.write_bytes(candidate.files[one.resolve()].read_bytes())
    recovered = PaperCandidate(tmp_path, 'front_matter', [one, two], lambda: 'inputs')
    assert one.read_bytes() == original and two.read_bytes() == original
    with recovered:
        assert 'First candidate' in read_text(one) and 'Second candidate' in read_text(two)


@pytest.mark.asyncio
async def test_failed_multifile_publication_rolls_back_all_outputs(tmp_path, monkeypatch):
    from server.services import paper_candidate_transaction as module
    one, two = setup(tmp_path, 'a.tex'), setup(tmp_path, 'b.tex')
    original = one.read_bytes()
    candidate = PaperCandidate(tmp_path, 'front_matter', [one, two], lambda: 'inputs')
    with candidate:
        await file_edit(str(one), 'Verified formula.', 'First candidate.')
        await file_edit(str(two), 'Verified formula.', 'Second candidate.')
    write, failed = module.atomic_write_bytes, []
    def failing_write(path, raw):
        if path == two and not failed:
            failed.append(True)
            raise OSError('disk error')
        write(path, raw)
    monkeypatch.setattr(module, 'atomic_write_bytes', failing_write)
    with pytest.raises(OSError, match='disk error'):
        candidate.publish({'passed': True})
    assert one.read_bytes() == original and two.read_bytes() == original


@pytest.mark.asyncio
async def test_recovery_never_erases_an_external_edit_after_partial_commit(tmp_path):
    one, two = setup(tmp_path, 'a.tex'), setup(tmp_path, 'b.tex')
    candidate = PaperCandidate(tmp_path, 'front_matter', [one, two], lambda: 'inputs')
    with candidate:
        await file_edit(str(one), 'Verified formula.', 'First candidate.')
    candidate.record('committing')
    one.write_bytes(candidate.files[one.resolve()].read_bytes())
    two.write_text('User wrote a later correction')
    with pytest.raises(ValueError, match='external edit'):
        PaperCandidate(tmp_path, 'front_matter', [one, two], lambda: 'inputs')
    assert two.read_text() == 'User wrote a later correction'
