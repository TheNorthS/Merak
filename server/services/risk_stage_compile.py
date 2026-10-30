"""Collect deterministic compile findings for the risk coordinator.

Finding generation does not grant artifact acceptance. Repair responsibility
remains with the producer identified by each finding, not a downstream consumer."""

from __future__ import annotations
from pathlib import Path
from typing import Any
import hashlib
import re
from .risk_artifact_support import _finding, _has_content, _json, _missing, _relative, _source_bundle_sha256, _text

class _EarlyReturn(BaseException):

    def __init__(self, value: Any):
        self.value = value

def _rule_1(root: Any) -> dict[str, Any]:
    tex = root / 'paper' / 'main.tex'
    pdf = root / 'paper' / 'main.pdf'
    build_path = root / 'paper' / 'PAPER_BUILD.json'
    findings: list[dict[str, Any]] = []
    if not _has_content(tex):
        findings.append(_missing('COMPILE-TEX-001', 'paper/main.tex'))
    if not _has_content(pdf):
        findings.append(_missing('COMPILE-PDF-001', 'paper/main.pdf'))
        raise _EarlyReturn(findings)
    try:
        signature = pdf.read_bytes()[:5]
    except OSError:
        signature = b''
    if signature != b'%PDF-':
        findings.append(_finding('COMPILE-PDF-002', 'blocker', 'build', 'paper/main.pdf does not have a PDF file signature.', 'paper/main.pdf 不是有效 PDF 文件，可能只是同名占位文件。', ['paper/main.pdf'], 'Compile main.tex with a real LaTeX engine and preserve the log.'))
    build, error = _json(build_path)
    compile_record = build.get('compile') or {} if isinstance(build, dict) else {}
    has_source_hash = bool(str(compile_record.get('source_bundle_sha256') or '').strip())
    source_hash, source_bundle_paths = _source_bundle_sha256(root / 'paper')
    newest_source = max((path.stat().st_mtime for path in source_bundle_paths), default=0.0)
    if not has_source_hash and newest_source and (pdf.stat().st_mtime + 1.0 < newest_source):
        findings.append(_finding('COMPILE-STALE-001', 'blocker', 'build', 'Compiled PDF is older than one or more included TeX or graphic sources.', 'PDF 早于当前 TeX 或引用图片，最终交付物是旧版本。', ['paper/main.pdf', *[_relative(root, path) for path in source_bundle_paths]], 'Recompile after the latest source revision.'))
    if error or not isinstance(build, dict):
        findings.append(_missing('COMPILE-BUILD-001', 'paper/PAPER_BUILD.json'))
    else:
        if not bool(compile_record.get('success')):
            findings.append(_finding('COMPILE-BUILD-002', 'blocker', 'build', 'PAPER_BUILD.json does not record a successful compile.', 'PAPER_BUILD.json 没有记录成功编译，不能仅凭 PDF 文件存在放行。', ['paper/PAPER_BUILD.json'], 'Persist compile success, page count, warnings, and current PDF path.'))
        try:
            pages = int(compile_record.get('pages') or 0)
        except (TypeError, ValueError):
            pages = 0
        if pages <= 0:
            findings.append(_finding('COMPILE-PAGES-001', 'warning', 'build', 'Build record does not contain a measured PDF page count.', '构建记录没有实际 PDF 页数；页数虽是软目标，但应基于编译结果而不是模型估计。', ['paper/PAPER_BUILD.json'], 'Measure and persist the compiled page count.'))
        if not str(compile_record.get('source_bundle_sha256') or '') or compile_record.get('source_bundle_sha256') != source_hash:
            findings.append(_finding('COMPILE-HASH-001', 'blocker', 'build', 'PAPER_BUILD source hash does not match the current TeX bundle.', 'PAPER_BUILD.json 的源文件哈希与当前 TeX 不一致，构建记录已经过期。', ['paper/PAPER_BUILD.json', 'paper/main.tex'], 'Recompile and refresh the hash-bound build record.'))
        current_pdf_hash = hashlib.sha256(pdf.read_bytes()).hexdigest()
        if not str(compile_record.get('pdf_sha256') or '') or compile_record.get('pdf_sha256') != current_pdf_hash:
            findings.append(_finding('COMPILE-HASH-002', 'blocker', 'build', 'PAPER_BUILD PDF hash does not match paper/main.pdf.', 'PAPER_BUILD.json 的 PDF 哈希与 main.pdf 不一致，交付物来源不可追溯。', ['paper/PAPER_BUILD.json', 'paper/main.pdf'], 'Refresh the build record from the verified PDF.'))
    log = _text(root / 'paper' / 'main.log')
    if not log:
        findings.append(_finding('COMPILE-LOG-001', 'warning', 'build', 'No LaTeX build log was retained.', '没有保留 LaTeX 编译日志，无法检查非致命排版问题和引用稳定性。', ['paper/main.log'], 'Retain the compiler log with the hash-bound build record.'))
    elif re.search('(?:!\\s+LaTeX\\s+Error|Emergency stop|Fatal error occurred)', log, re.IGNORECASE):
        findings.append(_finding('COMPILE-LOG-002', 'blocker', 'build', 'LaTeX log contains a fatal compilation error despite a PDF artifact.', 'LaTeX 日志仍包含致命错误，即使目录里有 PDF，也可能是旧文件或部分输出。', ['paper/main.log', 'paper/main.pdf'], 'Fix the source and produce a clean current compile.'))
    if re.search('(?:undefined references|citation.+undefined|there were undefined)', log, re.IGNORECASE):
        findings.append(_finding('COMPILE-REF-001', 'blocker', 'build', 'LaTeX log contains unresolved citations or references.', 'LaTeX 日志仍有未解析的引用或交叉引用。', ['paper/main.log'], 'Repair labels/BibTeX and compile until references stabilize.'))
    return {key: value for key, value in locals().items() if key in ['build', 'build_path', 'compile_record', 'current_pdf_hash', 'error', 'findings', 'has_source_hash', 'log', 'newest_source', 'pages', 'pdf', 'signature', 'source_bundle_paths', 'source_hash', 'tex']}

def _rule_2(build_path: Any, findings: Any, log: Any, root: Any) -> dict[str, Any]:
    if re.search('(?:Overfull \\\\hbox|Overfull \\\\vbox)', log):
        findings.append(_finding('COMPILE-LAYOUT-001', 'warning', 'layout', 'LaTeX log reports overfull boxes.', '编译日志存在 overfull box，正文、表格或公式可能越过版心。', ['paper/main.log'], 'Inspect the rendered pages and repair the affected layout without shrinking scientific content globally.'))
    build, _ = _json(build_path)
    from .paper_budget import paper_budget_service
    budget = paper_budget_service.load(root)
    if budget and isinstance(build, dict):
        compile_record = build.get('compile') if isinstance(build.get('compile'), dict) else {}
        try:
            actual_pages = int(compile_record.get('pages') or 0)
            minimum = budget.minimum_pages
            maximum = budget.maximum_pages
        except (TypeError, ValueError):
            actual_pages = minimum = maximum = 0
        if actual_pages and minimum and maximum and (not minimum <= actual_pages <= maximum):
            findings.append(_finding('COMPILE-BUDGET-001', 'warning', 'paper_length', f'Compiled paper has {actual_pages} pages; preferred range is {minimum}-{maximum}.', f'论文实际 {actual_pages} 页，用户偏好范围为 {minimum}-{maximum} 页；这是软目标，不能用填充或格式扭曲强行满足。', ['paper/PAPER_BUDGET.json', 'paper/PAPER_BUILD.json'], 'Adjust only when grounded scientific detail can be added or repetition can be removed.'))
    return {key: value for key, value in locals().items() if key in ['_', 'actual_pages', 'budget', 'build', 'compile_record', 'maximum', 'minimum', 'paper_budget_service']}

def audit(service: Any, root: Path, options: dict[str, Any]) -> list[dict[str, Any]]:
    state = {'root': root, 'service': service, 'options': options}
    try:
        state.update(_rule_1(root=state['root']))
        state.update(_rule_2(build_path=state['build_path'], findings=state['findings'], log=state['log'], root=state['root']))
    except _EarlyReturn as returned:
        return returned.value
    return state.get('findings', [])
