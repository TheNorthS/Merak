"""
论文编译服务 — LaTeX → PDF

功能：
- latexmk 编译
- 错误/警告解析
- BibTeX 条目解析（用于前端自动补全）
- PDF 生成 + 文件服务
- SyncTeX 支持
- 会议模板管理
"""

import asyncio
import locale
import re
import subprocess
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional

import structlog

from .paper_build_record import refresh_build_record
from .pdf_review_inspection import inspect_pdf_for_review
from .latex_source_repair import LatexSourceRepair
from .latex_compile_execution import compile_paper
from .local_compile_process import run_local_compile_process
from .paper_templates import (
    VENUE_MAIN_TEX as VENUE_MAIN_TEX,
    VENUE_TEMPLATES as VENUE_TEMPLATES,
    scaffold_paper as scaffold_paper,
    scaffold_paper_files as scaffold_paper_files,
)

logger = structlog.get_logger()


@dataclass
class CompileError:
    """编译错误"""
    file: str
    line: int
    message: str
    severity: str  # "error" | "warning" | "info"


@dataclass
class CompileResult:
    """编译结果"""
    success: bool
    pdf_path: Optional[str] = None
    errors: list[CompileError] = field(default_factory=list)
    warnings: list[CompileError] = field(default_factory=list)
    log_output: str = ""
    compile_time_ms: int = 0
    pages: int = 0
    source_repairs: list[dict[str, object]] = field(default_factory=list)


@dataclass
class BibEntry:
    """BibTeX 条目"""
    key: str
    entry_type: str  # article, inproceedings, book, etc.
    title: str = ""
    authors: str = ""
    year: str = ""
    venue: str = ""  # journal or booktitle
    raw: str = ""


class PaperCompiler(LatexSourceRepair):
    """论文编译器"""

    def __init__(self):
        self._compile_locks: dict[str, asyncio.Lock] = {}

    def _compile_lock_for(self, project_path: Path) -> asyncio.Lock:
        key = str(project_path.resolve()).replace("\\", "/").casefold()
        lock = self._compile_locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            self._compile_locks[key] = lock
        return lock

    @staticmethod
    async def _run_command(
        command: list[str],
        *,
        cwd: str | None = None,
        timeout: int,
        stderr: int = subprocess.STDOUT,
    ) -> subprocess.CompletedProcess[bytes]:
        """Run a renderer without relying on asyncio subprocess support on Windows."""
        return await asyncio.to_thread(
            run_local_compile_process,
            command,
            cwd=cwd,
            stderr=stderr,
            timeout=timeout,
        )

    @staticmethod
    def _decode_process_output(value: bytes | None) -> str:
        raw = value or b""
        encodings = (
            "utf-8",
            locale.getpreferredencoding(False) or "utf-8",
            "gb18030",
        )
        for encoding in dict.fromkeys(encodings):
            try:
                return raw.decode(encoding, errors="strict")
            except (LookupError, UnicodeDecodeError):
                continue
        return raw.decode("utf-8", errors="replace")

    async def compile(
        self,
        project_dir: str,
        main_tex: str = "main.tex",
        clean: bool = False,
    ) -> CompileResult:
        return await compile_paper(
            self, CompileResult, CompileError, project_dir, main_tex, clean,
        )

    def _parse_errors(self, log: str) -> list[CompileError]:
        """解析 LaTeX 错误"""
        errors = []
        # 匹配 file:line: error message
        error_pattern = re.compile(r'^(.+?):(\d+):\s*(.+?)$', re.MULTILINE)
        for match in error_pattern.finditer(log):
            errors.append(CompileError(
                file=match.group(1).strip(),
                line=int(match.group(2)),
                message=match.group(3).strip(),
                severity="error",
            ))

        # 匹配 ! LaTeX Error
        latex_error_pattern = re.compile(r'^!\s*(.+?)$', re.MULTILINE)
        for match in latex_error_pattern.finditer(log):
            msg = match.group(1).strip()
            if msg and not any(e.message == msg for e in errors):
                errors.append(CompileError(file="", line=0, message=msg, severity="error"))

        return errors[:20]  # 最多20个错误

    def _parse_warnings(self, log: str) -> list[CompileError]:
        """解析 LaTeX 警告"""
        warnings = []
        warning_pattern = re.compile(r'LaTeX Warning:\s*(.+?)(?:\n|$)', re.MULTILINE)
        for match in warning_pattern.finditer(log):
            warnings.append(CompileError(
                file="", line=0,
                message=match.group(1).strip(),
                severity="warning",
            ))

        # Overfull/Underfull boxes
        box_pattern = re.compile(r'(Overfull|Underfull)\s+\\[hv]box.+?at lines?\s+(\d+)', re.MULTILINE)
        for match in box_pattern.finditer(log):
            warnings.append(CompileError(
                file="", line=int(match.group(2)),
                message=f"{match.group(1)} box",
                severity="warning",
            ))

        unique: list[CompileError] = []
        seen: set[tuple[str, int, str]] = set()
        for warning in warnings:
            key = (warning.file, warning.line, warning.message)
            if key in seen:
                continue
            seen.add(key)
            unique.append(warning)
        return unique[:30]

    async def _get_page_count(self, pdf_path: str) -> int:
        """Read the generated PDF directly; use pdfinfo only as a fallback."""
        try:
            from pypdf import PdfReader

            pages = await asyncio.to_thread(lambda: len(PdfReader(pdf_path).pages))
            if pages > 0:
                return pages
        except Exception as exc:
            logger.warning("pypdf page count failed", path=pdf_path, error=str(exc))

        try:
            result = await self._run_command(
                ["pdfinfo", pdf_path],
                timeout=10,
                stderr=subprocess.DEVNULL,
            )
            match = re.search(
                r'Pages:\s+(\d+)',
                self._decode_process_output(result.stdout),
            )
            return int(match.group(1)) if match else 0
        except Exception as exc:
            logger.warning("pdfinfo page count failed", path=pdf_path, error=str(exc))
            return 0

    inspect_pdf_for_review = staticmethod(inspect_pdf_for_review)

    refresh_build_record = staticmethod(refresh_build_record)


class BibManager:
    """BibTeX 管理器"""

    def parse_bib_file(self, bib_path: str) -> list[BibEntry]:
        """解析 .bib 文件"""
        try:
            content = Path(bib_path).read_text(encoding='utf-8')
            return self._parse_bibtex(content)
        except Exception as e:
            logger.error("Failed to parse bib file", path=bib_path, error=str(e))
            return []

    def parse_bib_content(self, content: str) -> list[BibEntry]:
        """解析 BibTeX 内容"""
        return self._parse_bibtex(content)

    def _parse_bibtex(self, content: str) -> list[BibEntry]:
        """解析 BibTeX"""
        entries = []
        # 匹配 @type{key, ... }
        entry_pattern = re.compile(
            r'@(\w+)\s*\{\s*([^,]+)\s*,([^@]*?)\}(?=\s*@|\s*$)',
            re.DOTALL
        )

        for match in entry_pattern.finditer(content):
            entry_type = match.group(1).lower()
            key = match.group(2).strip()
            fields_str = match.group(3)

            if entry_type in ('comment', 'string', 'preamble'):
                continue

            # 解析字段
            fields = self._parse_fields(fields_str)

            entries.append(BibEntry(
                key=key,
                entry_type=entry_type,
                title=fields.get('title', ''),
                authors=fields.get('author', ''),
                year=fields.get('year', ''),
                venue=fields.get('journal', '') or fields.get('booktitle', ''),
                raw=match.group(0),
            ))

        return entries

    def _parse_fields(self, fields_str: str) -> dict[str, str]:
        """解析 BibTeX 字段"""
        fields = {}
        # 简单匹配 key = {value} 或 key = "value"
        field_pattern = re.compile(r'(\w+)\s*=\s*[{"]([^}"]*)[}"]', re.DOTALL)
        for match in field_pattern.finditer(fields_str):
            key = match.group(1).lower()
            value = match.group(2).strip().replace('\n', ' ')
            # 清理多余空格
            value = re.sub(r'\s+', ' ', value)
            fields[key] = value
        return fields

    def get_citation_keys(self, bib_path: str) -> list[str]:
        """获取所有引用 key（用于自动补全）"""
        entries = self.parse_bib_file(bib_path)
        return [e.key for e in entries]

    def search_entries(self, entries: list[BibEntry], query: str) -> list[BibEntry]:
        """搜索 BibTeX 条目"""
        q = query.lower()
        return [
            e for e in entries
            if q in e.key.lower() or q in e.title.lower() or q in e.authors.lower()
        ]


# 全局实例
paper_compiler = PaperCompiler()
bib_manager = BibManager()
