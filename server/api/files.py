"""File operations authorized by desktop capability or project membership."""

from fastapi import APIRouter, HTTPException, Depends
from .access import authorize_files
from fastapi.responses import FileResponse
from pydantic import BaseModel
from pathlib import Path
from typing import List, Optional
import aiofiles
import asyncio
import os
import subprocess
import sys
import shutil
import zipfile

from ..utils.atomic_write import atomic_write_text

router = APIRouter(dependencies=[Depends(authorize_files)])


def _validate_pptx_archive(path: Path) -> None:
    with zipfile.ZipFile(path) as archive:
        members = archive.infolist()
        total_uncompressed = sum(item.file_size for item in members)
        if len(members) > 5000 or total_uncompressed > 500 * 1024 * 1024:
            raise HTTPException(
                status_code=413,
                detail="PPTX archive expands beyond the safe parsing limit",
            )
        if any(item.file_size > 100 * 1024 * 1024 for item in members):
            raise HTTPException(
                status_code=413,
                detail="PPTX contains an oversized archive member",
            )


def _create_empty_exclusive(path: Path) -> None:
    path.touch(exist_ok=False)


class FileInfo(BaseModel):
    name: str
    path: str
    is_directory: bool
    size: int = 0
    modified: float = 0


class FileContent(BaseModel):
    path: str
    content: str
    encoding: str = "utf-8"


class CreateRequest(BaseModel):
    path: str
    is_directory: bool = False


class RenameRequest(BaseModel):
    old_path: str
    new_path: str


class DeleteRequest(BaseModel):
    path: str


# ==================== 目录与文件浏览 ====================

@router.get("/list", response_model=List[FileInfo])
async def list_files(path: str):
    """列出目录内容"""
    dir_path = Path(path)
    if not dir_path.exists() or not dir_path.is_dir():
        raise HTTPException(status_code=404, detail="Directory not found")

    entries = []
    skip = {'.git', 'node_modules', '__pycache__', 'dist', 'dist-electron', '.merak', '.venv', 'venv'}
    for entry in sorted(dir_path.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower())):
        if not entry.resolve().is_relative_to(dir_path.resolve()):
            continue
        if entry.name.startswith('.') and entry.name not in ('.env.example',):
            continue
        if entry.name in skip:
            continue
        try:
            stat = entry.stat()
            entries.append(FileInfo(
                name=entry.name,
                path=str(entry),
                is_directory=entry.is_dir(),
                size=stat.st_size,
                modified=stat.st_mtime,
            ))
        except (PermissionError, OSError):
            continue
    return entries


@router.get("/read")
async def read_file(path: str):
    """读取文件内容（文本）"""
    file_path = Path(path)
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    if file_path.stat().st_size > 10 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="File too large (>10MB)")
    try:
        async with aiofiles.open(file_path, 'r', encoding='utf-8') as f:
            content = await f.read()
        return {"path": str(file_path), "content": content}
    except UnicodeDecodeError:
        raise HTTPException(status_code=415, detail="Binary file")


@router.get("/read-binary")
async def read_binary(path: str):
    """读取二进制文件（PDF/PPTX 等），自动设置正确的 MIME type"""
    file_path = Path(path)
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    if file_path.stat().st_size > 512 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Binary file is too large (>512MB)")

    # 根据扩展名设置 MIME type
    ext = file_path.suffix.lower()
    mime_map = {
        '.pdf': 'application/pdf',
        '.pptx': 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
        '.png': 'image/png',
        '.jpg': 'image/jpeg',
        '.jpeg': 'image/jpeg',
        '.svg': 'image/svg+xml',
        '.webp': 'image/webp',
        '.gif': 'image/gif',
    }
    media_type = mime_map.get(ext, 'application/octet-stream')
    return FileResponse(
        str(file_path),
        media_type=media_type,
        headers={
            "Content-Security-Policy": "sandbox; default-src 'none'; style-src 'unsafe-inline'",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.post("/write")
async def write_file(data: FileContent):
    """写入文件（创建或覆盖）"""
    file_path = Path(data.path).expanduser().resolve()
    try:
        await asyncio.to_thread(
            atomic_write_text,
            file_path,
            data.content,
            encoding=data.encoding,
        )
    except (LookupError, OSError, UnicodeError) as exc:
        raise HTTPException(status_code=500, detail=f"Unable to write file: {exc}") from exc

    figure_refresh = None
    if file_path.suffix.lower() in {".mmd", ".mermaid", ".excalidraw"}:
        try:
            from ..services.figure_engine import figure_engine

            figure_refresh = await figure_engine.refresh_editable_source(file_path)
        except Exception as exc:
            figure_refresh = {"success": False, "error": str(exc)}

    return {
        "status": "written",
        "path": str(file_path),
        "figure_refresh": figure_refresh,
    }


# ==================== 创建 / 删除 / 重命名 ====================

@router.post("/create")
async def create_file_or_dir(req: CreateRequest):
    """新建文件或文件夹"""
    p = Path(req.path)
    if p.exists():
        raise HTTPException(status_code=409, detail="Already exists")
    try:
        if req.is_directory:
            p.mkdir(parents=True, exist_ok=False)
        else:
            p.parent.mkdir(parents=True, exist_ok=True)
            await asyncio.to_thread(_create_empty_exclusive, p)
        return {"status": "created", "path": str(p), "is_directory": req.is_directory}
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail="Already exists") from exc
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/delete")
async def delete_file_or_dir(req: DeleteRequest):
    """删除文件或文件夹"""
    p = Path(req.path).expanduser()
    if not p.exists() and not p.is_symlink():
        raise HTTPException(status_code=404, detail="Not found")
    resolved = p.resolve()
    protected_roots = {
        Path(resolved.anchor).resolve(),
        Path.home().resolve(),
        Path.cwd().resolve(),
    }
    if resolved in protected_roots:
        raise HTTPException(status_code=409, detail="Refusing to delete a protected root directory")
    if p.is_dir() and not p.is_symlink() and any(
        (p / marker).exists() for marker in (".git", ".merak")
    ):
        raise HTTPException(
            status_code=409,
            detail="Refusing to recursively delete a repository or MERAK project root",
        )
    try:
        if p.is_symlink():
            p.unlink()
        elif p.is_dir():
            shutil.rmtree(str(p))
        else:
            p.unlink()
        return {"status": "deleted", "path": str(p)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/rename")
async def rename_file(req: RenameRequest):
    """重命名/移动"""
    p = Path(req.old_path)
    if not p.exists():
        raise HTTPException(status_code=404, detail="Source not found")
    destination = Path(req.new_path)
    if destination.exists():
        raise HTTPException(status_code=409, detail="Destination already exists")
    try:
        p.rename(destination)
        return {"status": "renamed", "old": req.old_path, "new": req.new_path}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ==================== 搜索 ====================

@router.get("/search")
async def search_files(root: str, query: str, glob_pattern: Optional[str] = None, mode: Optional[str] = None):
    """搜索文件内容或文件名"""
    root_path = Path(root)
    if not root_path.exists():
        raise HTTPException(status_code=404, detail="Root not found")

    results = []
    max_results = 50
    pattern = glob_pattern or "**/*"
    normalized_pattern = pattern.replace("\\", "/")
    if Path(pattern).is_absolute() or ".." in normalized_pattern.split("/"):
        raise HTTPException(status_code=422, detail="Search pattern must stay within root")

    if mode == "filename":
        for f in root_path.rglob("*"):
            if not f.resolve().is_relative_to(root_path.resolve()):
                continue
            if query.lower() in f.name.lower():
                results.append({"path": str(f), "line": 0, "text": f.name})
            if len(results) >= max_results:
                break
    else:
        for file_path in root_path.glob(pattern):
            if not file_path.resolve().is_relative_to(root_path.resolve()):
                continue
            if len(results) >= max_results:
                break
            if not file_path.is_file() or file_path.stat().st_size > 1024 * 1024:
                continue
            try:
                content = file_path.read_text(encoding='utf-8')
                for i, line in enumerate(content.splitlines(), 1):
                    if query.lower() in line.lower():
                        results.append({"path": str(file_path), "line": i, "text": line.strip()[:200]})
                        if len(results) >= max_results:
                            break
            except (UnicodeDecodeError, PermissionError):
                continue

    return {"query": query, "results": results, "total": len(results)}


# ==================== 用系统默认程序打开 ====================

class OpenExternalRequest(BaseModel):
    path: str


@router.post("/open-external")
async def open_external(request: OpenExternalRequest):
    """用系统默认程序打开文件"""
    file_path = Path(request.path)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")
    try:
        if sys.platform == 'win32':
            os.startfile(str(file_path))
        elif sys.platform == 'darwin':
            subprocess.Popen(['open', str(file_path)])
        else:
            subprocess.Popen(['xdg-open', str(file_path)])
        return {"status": "opened", "path": str(file_path)}
    except OSError as e:
        raise HTTPException(status_code=500, detail=f"Unable to open file: {e}") from e


# ==================== LaTeX 编译 ====================

class LatexCompileRequest(BaseModel):
    project_dir: str
    main_tex: str = "main.tex"


@router.post("/latex-compile")
async def latex_compile(request: LatexCompileRequest):
    """Compile through the canonical service used by workflow paper nodes."""
    project_dir = Path(request.project_dir)
    tex_file = project_dir / request.main_tex

    if not tex_file.exists():
        return {"success": False, "error": f"File not found: {request.main_tex}", "output": ""}
    from ..services.paper_compiler import paper_compiler

    result = await paper_compiler.compile(
        project_dir=str(project_dir),
        main_tex=request.main_tex,
        clean=False,
    )
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
    errors = [
        f"{item.file + ':' if item.file else ''}{item.line or ''} {item.message}".strip()
        for item in result.errors
    ]
    return {
        "success": result.success,
        "pdf": result.pdf_path,
        "pages": result.pages,
        "compiler": "latexmk",
        "output": result.log_output,
        "error": "\n".join(errors[:10]) if errors else "",
        "warnings": [item.message for item in result.warnings],
    }


# ==================== PPTX 解析 ====================

@router.get("/pptx-slides")
async def get_pptx_slides(path: str):
    """解析 PPTX 文件，返回每页幻灯片的内容"""
    from pptx import Presentation as PptxPresentation
    import base64

    file_path = Path(path)
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    if file_path.suffix.casefold() != ".pptx":
        raise HTTPException(status_code=415, detail="Only .pptx files are supported")
    if file_path.stat().st_size > 100 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="PPTX file is too large (>100MB)")

    try:
        _validate_pptx_archive(file_path)
        prs = PptxPresentation(str(file_path))
        if len(prs.slides) > 500:
            raise HTTPException(status_code=413, detail="PPTX contains too many slides")
        slides = []
        embedded_image_bytes = 0

        for i, slide in enumerate(prs.slides):
            slide_data = {"index": i, "texts": [], "images": []}

            for shape in slide.shapes:
                if shape.has_text_frame:
                    for para in shape.text_frame.paragraphs:
                        text = para.text.strip()
                        if text:
                            # 判断是标题还是正文
                            is_title = shape == slide.shapes.title if slide.shapes.title else False
                            slide_data["texts"].append({
                                "text": text,
                                "is_title": is_title,
                                "bold": any(run.font.bold for run in para.runs if run.font.bold),
                                "size": max((run.font.size.pt if run.font.size else 18) for run in para.runs) if para.runs else 18,
                            })

                if shape.shape_type == 13:  # Picture
                    try:
                        img = shape.image
                        img_bytes = img.blob
                        embedded_image_bytes += len(img_bytes)
                        if (
                            len(img_bytes) > 16 * 1024 * 1024
                            or embedded_image_bytes > 64 * 1024 * 1024
                        ):
                            raise HTTPException(
                                status_code=413,
                                detail="PPTX embedded images exceed the preview limit",
                            )
                        img_b64 = base64.b64encode(img_bytes).decode('ascii')
                        slide_data["images"].append({
                            "data": f"data:{img.content_type};base64,{img_b64}",
                            "width": shape.width,
                            "height": shape.height,
                        })
                    except (AttributeError, TypeError, ValueError):
                        # Some non-picture shapes expose a placeholder image
                        # attribute which python-pptx cannot materialize.
                        continue

            slides.append(slide_data)

        return {"total": len(slides), "slides": slides, "width": prs.slide_width, "height": prs.slide_height}

    except HTTPException:
        raise
    except (zipfile.BadZipFile, ValueError, KeyError) as exc:
        raise HTTPException(status_code=422, detail="Invalid or unsupported PPTX file") from exc
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Unable to read PPTX: {exc}") from exc
