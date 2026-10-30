from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from server.services.paper_compiler import CompileResult, paper_compiler


@pytest.fixture
def review_pdf_compiler(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, str]]:
    """Install a deterministic LaTeX/PDF boundary for managed-review tests."""
    calls: list[dict[str, str]] = []

    async def fake_compile(
        project_dir: str,
        main_tex: str = "main.tex",
        clean: bool = False,
    ) -> CompileResult:
        paper_dir = Path(project_dir)
        source = paper_dir / main_tex
        source_text = source.read_text(encoding="utf-8")
        digest = hashlib.sha256(source_text.encode("utf-8")).hexdigest()
        pdf = source.with_suffix(".pdf")
        pdf.write_bytes(
            b"%PDF-1.4\n% managed review test fixture\n"
            + digest.encode("ascii")
            + b"\n%%EOF\n"
        )
        calls.append({
            "project_dir": str(paper_dir),
            "main_tex": main_tex,
            "clean": str(clean),
            "source_sha256": digest,
        })
        return CompileResult(
            success=True,
            pdf_path=str(pdf),
            pages=1,
        )

    def fake_inspect(
        pdf_path: str | Path,
        *,
        preview_dir: str | Path,
        max_pages: int = 40,
    ) -> dict[str, object]:
        del max_pages
        preview_root = Path(preview_dir)
        preview_root.mkdir(parents=True, exist_ok=True)
        page_preview = preview_root / "page-001.png"
        contact_sheet = preview_root / "contact-sheet.png"
        page = Image.new("RGB", (1200, 1600), "#ffffff")
        draw = ImageDraw.Draw(page)
        draw.rectangle((80, 80, 1120, 1520), outline="#111827", width=4)
        draw.text(
            (140, 180),
            "Managed review fixture: rendered manuscript page",
            fill="#111827",
        )
        draw.text(
            (140, 260),
            hashlib.sha256(Path(pdf_path).read_bytes()).hexdigest(),
            fill="#334155",
        )
        page.save(page_preview, format="PNG")
        page.resize((600, 800)).save(contact_sheet, format="PNG")
        return {
            "schema": 1,
            "pdf_path": str(pdf_path),
            "pdf_sha256": hashlib.sha256(Path(pdf_path).read_bytes()).hexdigest(),
            "page_count": 1,
            "renderer": "test-layout-renderer",
            "rendered_page_previews": [str(page_preview)],
            "contact_sheet_paths": [str(contact_sheet)],
            "document_findings": [],
            "pages": [{
                "page": 1,
                "width_pt": 612.0,
                "height_pt": 792.0,
                "visible_text_chars": 120,
                "possible_layout_findings": [],
            }],
        }

    monkeypatch.setattr(paper_compiler, "compile", fake_compile)
    monkeypatch.setattr(
        paper_compiler,
        "inspect_pdf_for_review",
        fake_inspect,
    )
    return calls
