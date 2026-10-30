"""论文编译与引用管理 API"""

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import List, Optional
from pathlib import Path

from ..services.paper_compiler import paper_compiler, bib_manager, VENUE_TEMPLATES, scaffold_paper

router = APIRouter()


class CompileRequest(BaseModel):
    project_dir: str
    main_tex: str = "main.tex"
    clean: bool = False


class ScaffoldRequest(BaseModel):
    project_dir: str
    venue: str
    title: str = "Your Paper Title"
    author: str = "Author Name"
    affiliation: str = "University"
    email: str = "author@example.com"
    abstract: str = "Your abstract here."


class CompileResponse(BaseModel):
    success: bool
    pdf_path: Optional[str]
    pages: int
    compile_time_ms: int
    errors: List[dict]
    warnings: List[dict]


class BibEntryResponse(BaseModel):
    key: str
    entry_type: str
    title: str
    authors: str
    year: str
    venue: str


@router.post("/compile")
async def compile_paper(request: CompileRequest):
    """编译 LaTeX 论文"""
    result = await paper_compiler.compile(
        project_dir=request.project_dir,
        main_tex=request.main_tex,
        clean=request.clean,
    )
    project_dir = Path(request.project_dir)
    if result.success and request.main_tex.casefold() == "main.tex":
        record_name = (
            "PAPER_BUILD.json"
            if project_dir.name.casefold() == "paper"
            else "SLIDE_BUILD.json"
            if project_dir.name.casefold() == "slides"
            else ""
        )
        if record_name:
            paper_compiler.refresh_build_record(
                project_dir,
                record_name,
                "main.pdf",
                pages=result.pages,
                compile_time_ms=result.compile_time_ms,
                warning_count=len(result.warnings),
            )
    return {
        "success": result.success,
        "pdf_path": result.pdf_path,
        "pages": result.pages,
        "compile_time_ms": result.compile_time_ms,
        "errors": [{"file": e.file, "line": e.line, "message": e.message, "severity": e.severity} for e in result.errors],
        "warnings": [{"file": w.file, "line": w.line, "message": w.message, "severity": w.severity} for w in result.warnings],
    }


@router.post("/scaffold")
async def scaffold(request: ScaffoldRequest):
    """从模板创建论文项目"""
    result = await scaffold_paper(
        project_dir=request.project_dir,
        venue=request.venue,
        title=request.title,
        author=request.author,
        affiliation=request.affiliation,
        email=request.email,
        abstract=request.abstract,
    )
    return result


@router.get("/pdf")
async def serve_pdf(path: str):
    """提供 PDF 文件"""
    pdf_path = Path(path)
    if not pdf_path.exists() or not pdf_path.suffix == '.pdf':
        raise HTTPException(status_code=404, detail="PDF not found")
    return FileResponse(str(pdf_path), media_type="application/pdf")


@router.get("/bib/parse")
async def parse_bib(path: str, query: Optional[str] = None):
    """解析 BibTeX 文件"""
    entries = bib_manager.parse_bib_file(path)
    if query:
        entries = bib_manager.search_entries(entries, query)
    return [
        {"key": e.key, "entry_type": e.entry_type, "title": e.title, "authors": e.authors, "year": e.year, "venue": e.venue}
        for e in entries
    ]


@router.get("/bib/keys")
async def get_bib_keys(path: str):
    """获取 BibTeX 引用 keys（用于编辑器自动补全）"""
    keys = bib_manager.get_citation_keys(path)
    return {"path": path, "keys": keys, "count": len(keys)}


@router.get("/venues")
async def list_venues():
    """列出支持的会议模板"""
    return {"venues": [{"id": k, **v} for k, v in VENUE_TEMPLATES.items()]}


@router.get("/venues/{venue_id}")
async def get_venue(venue_id: str):
    """获取会议模板详情"""
    venue = VENUE_TEMPLATES.get(venue_id)
    if not venue:
        raise HTTPException(status_code=404, detail="Venue not found")
    return {"id": venue_id, **venue}
