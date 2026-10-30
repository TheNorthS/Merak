"""A wrapper exit code must not hide a concrete TeX error in its final log."""

from datetime import datetime
from types import SimpleNamespace

import pytest

from server.services.paper_compiler import PaperCompiler, CompileResult
from server.services.latex_compile_execution import _result_from_process


@pytest.mark.asyncio
async def test_wrapped_tex_line_is_reported_before_latexmk_failure(tmp_path):
    source = tmp_path/'main.tex';source.write_text('Invalid math')
    (tmp_path/'main.log').write_text('D:/research/slides/main.tex:2\n69: Missing $ inserted.\n')
    process = SimpleNamespace(returncode=12, stdout=b'D:/latex/runscript.tlu:922: command failed with exit code 12')
    result = await _result_from_process(PaperCompiler(), process, tmp_path, source, 'main.tex',
                                       datetime.utcnow(), [], CompileResult)
    assert not result.success
    assert result.errors[0].line == 269 and result.errors[0].message == 'Missing $ inserted.'
