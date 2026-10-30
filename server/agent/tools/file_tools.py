"""Focused file tools for the MERAK agent surface."""

from __future__ import annotations

from pathlib import Path

import structlog

from ...utils.atomic_write import atomic_write_text, path_lock
from ...services.paper_candidate_io import candidate_path, candidate_write_guard
from .manuscript_write_feedback import manuscript_write_feedback


logger = structlog.get_logger()
FILE_READ_MAX_CHARS = 128_000


async def file_read(path: str, start_line: int = 0, end_line: int = 0) -> str:
    """读取文件内容；行号参数采用从 1 开始、首尾均包含的语义。"""
    p = candidate_path(Path(path))
    if not p.exists():
        raise FileNotFoundError(f"File not found: {path}")
    if start_line or end_line:
        start = max(0, start_line - 1) if start_line else 0
        end = end_line if end_line else None
        selected: list[str] = []
        selected_chars = 0
        truncated = False
        with p.open("r", encoding="utf-8-sig") as handle:
            for index, line in enumerate(handle):
                if index < start:
                    continue
                if end is not None and index >= end:
                    break
                clean = line.rstrip("\r\n")
                projected = selected_chars + len(clean) + (1 if selected else 0)
                if projected > FILE_READ_MAX_CHARS:
                    truncated = True
                    break
                selected.append(clean)
                selected_chars = projected
        content = "\n".join(selected)
    else:
        with p.open("r", encoding="utf-8-sig") as handle:
            content = handle.read(FILE_READ_MAX_CHARS + 1)
        truncated = len(content) > FILE_READ_MAX_CHARS
        if truncated:
            content = content[:FILE_READ_MAX_CHARS]

    if not truncated:
        return content
    return (
        content
        + "\n\n[MERAK Read truncated this file at "
        + f"{FILE_READ_MAX_CHARS} characters; file_bytes={p.stat().st_size}. "
        + "Use start_line/end_line for a bounded slice or Grep for targeted evidence. "
        + "The full file was not inserted into the model context.]"
    )


async def file_write(path: str, content: str) -> str:
    """写入文件（创建或覆盖）

    自动规范化路径：如果文件不属于任何约定目录，放入 misc/
    Corpus Write Guard：禁止写入受保护路径（skills/、shared-references/）
    """
    p = Path(path)

    # Corpus Write Guard — 阻止写入受保护的 skill/reference 目录
    protected_patterns = ['skills/', 'shared-references/', 'merak-skills/']
    path_str = str(p).replace('\\', '/')
    for pattern in protected_patterns:
        if pattern in path_str:
            raise PermissionError(
                f"BLOCKED: Cannot write to protected path '{path}'. "
                f"Skills and shared-references are read-only for the agent. "
                f"Use meta_optimize_propose to suggest changes instead."
            )

    # 如果是相对路径且不在约定目录内，归入 misc/
    if not p.is_absolute():
        known_prefixes = ['literature', 'ideas', 'experiments', 'paper', 'figures', 'slides', '.merak', 'misc']
        known_root_files = {'NARRATIVE_REPORT.md'}
        parts = p.parts
        if parts and parts[0] not in known_prefixes and str(p).replace('\\', '/') not in known_root_files:
            p = Path('misc') / p

    candidate_write_guard(p)
    p = candidate_path(p, writing=True)
    p.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(p, content)
    return f"Written {len(content)} bytes to {p}" + manuscript_write_feedback(p, content)


async def file_edit(path: str, old_text: str, new_text: str) -> str:
    """精确替换文件中的文本段"""
    if not old_text:
        raise ValueError("old_text must be nonempty; use Write for a new file")
    candidate_write_guard(Path(path), old_text)
    p = candidate_path(Path(path), writing=True)
    if not p.exists():
        raise FileNotFoundError(f"File not found: {path}")
    with path_lock(p):
        content = p.read_text(encoding='utf-8')
        if old_text not in content:
            raise ValueError("old_text not found in file")
        if content.count(old_text) != 1:
            raise ValueError("old_text is ambiguous; include more surrounding text for a unique match")
        content = content.replace(old_text, new_text, 1)
        atomic_write_text(p, content)
    return f"Edited {path}: replaced {len(old_text)} chars with {len(new_text)} chars" + manuscript_write_feedback(p, content)


async def file_list(directory: str, pattern: str = "*") -> str:
    """列出目录内容"""
    p = Path(directory)
    if not p.exists():
        raise FileNotFoundError(f"Directory not found: {directory}")
    entries = sorted(p.glob(pattern))
    result = []
    for e in entries[:100]:
        prefix = "📁" if e.is_dir() else "📄"
        result.append(f"{prefix} {e.name}")
    return '\n'.join(result)


async def file_search(directory: str, pattern: str, content_query: str = "") -> str:
    """搜索文件"""
    p = Path(directory)
    # Accept the common unambiguous model call that passes an exact file as
    # ``directory``.  Without this normalization a valid manifest is reported
    # as missing and downstream agents waste a repair round.
    if p.is_file():
        matches = p.match(pattern) or p.name == pattern
        if matches and content_query:
            try:
                matches = content_query.casefold() in candidate_path(p).read_text(
                    encoding="utf-8-sig", errors="replace"
                ).casefold()
            except OSError:
                matches = False
        return str(p) if matches else "No files found"
    results = []
    for f in p.rglob(pattern):
        if f.is_file():
            if content_query:
                try:
                    text = candidate_path(f).read_text(encoding='utf-8')
                    if content_query.lower() in text.lower():
                        results.append(str(f))
                except (OSError, UnicodeError) as exc:
                    logger.debug(
                        "Search skipped unreadable file",
                        path=str(f),
                        error=str(exc),
                    )
            else:
                results.append(str(f))
        if len(results) >= 50:
            break
    return '\n'.join(results) if results else "No files found"


# ==================== 终端执行 ====================

