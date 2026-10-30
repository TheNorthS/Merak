from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

from server.services.paper_compiler import paper_compiler


def test_process_output_decoder_handles_utf8_and_windows_gbk() -> None:
    message = "中文路径"
    assert paper_compiler._decode_process_output(message.encode("utf-8")) == message
    assert paper_compiler._decode_process_output(message.encode("gb18030")) == message


def test_compile_rejects_main_tex_outside_project_directory(tmp_path: Path) -> None:
    project = tmp_path / "paper"
    project.mkdir()
    outside = tmp_path / "outside.tex"
    outside.write_text("\\documentclass{article}", encoding="utf-8")

    result = asyncio.run(
        paper_compiler.compile(str(project), main_tex="../outside.tex")
    )

    assert result.success is False
    assert "inside" in result.errors[0].message


def test_warning_parser_deduplicates_repeated_layout_noise() -> None:
    log = (
        "Underfull \\hbox (badness 10000) in paragraph at lines 16--16\n"
        "Underfull \\hbox (badness 10000) in paragraph at lines 16--16\n"
    )
    warnings = paper_compiler._parse_warnings(log)
    assert [(item.message, item.line) for item in warnings] == [("Underfull box", 16)]


def test_pdf_review_inspection_renders_pages_and_layout_evidence(
    tmp_path: Path,
) -> None:
    import fitz

    pdf = tmp_path / "main_round0_original.pdf"
    document = fitz.open()
    first = document.new_page(width=612, height=792)
    first.insert_text(
        (72, 72),
        "A rendered manuscript page with enough text for layout inspection.",
        fontsize=10,
    )
    second = document.new_page(width=612, height=792)
    second.insert_text(
        (72, 72),
        "Second page used to verify page-by-page visual evidence.",
        fontsize=10,
    )
    document.save(pdf)
    document.close()

    report = paper_compiler.inspect_pdf_for_review(
        pdf,
        preview_dir=tmp_path / "previews",
    )

    assert report["renderer"] == "pymupdf"
    assert report["page_count"] == 2
    assert report["page_size_consistent"] is True
    assert len(report["pages"]) == 2
    assert all(
        Path(path).is_file()
        for path in report["rendered_page_previews"]
    )
    assert all(
        Path(path).is_file()
        for path in report["contact_sheet_paths"]
    )
    assert report["pages"][0]["median_font_pt"] == 10.0


def test_clean_compile_waits_for_cleanup_before_starting_latexmk(
    tmp_path: Path,
    monkeypatch,
) -> None:
    paper_dir = tmp_path / "paper"
    paper_dir.mkdir()
    (paper_dir / "main.tex").write_text(
        r"\documentclass{article}\begin{document}Test\end{document}",
        encoding="utf-8",
    )
    events: list[str] = []

    async def fake_run(args, **_kwargs):
        kind = "clean" if "-C" in args else "compile"
        events.append(f"run:{kind}")
        if kind == "compile":
            assert "run:clean" in events
            (paper_dir / "main.pdf").write_bytes(b"%PDF-1.4\n%%EOF\n")
            (paper_dir / "main.log").write_text(
                "Final pass completed without unresolved references.\n",
                encoding="utf-8",
            )
        return subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout=(
                b"LaTeX Warning: Reference `old-pass' undefined.\n"
                b"Latexmk: All targets are up-to-date\n"
            ),
        )

    async def unsupported_async_subprocess(*_args, **_kwargs):
        raise NotImplementedError

    async def fake_page_count(_path: str) -> int:
        return 1

    monkeypatch.setattr(asyncio, "create_subprocess_exec", unsupported_async_subprocess)
    monkeypatch.setattr(paper_compiler, "_run_command", fake_run)
    monkeypatch.setattr(paper_compiler, "_get_page_count", fake_page_count)

    result = asyncio.run(paper_compiler.compile(str(paper_dir), clean=True))

    assert result.success is True
    assert events == ["run:clean", "run:compile"]
    assert result.warnings == []


def test_repair_common_source_dependencies_adds_only_missing_packages(
    tmp_path: Path,
) -> None:
    paper_dir = tmp_path / "paper"
    sections_dir = paper_dir / "sections"
    sections_dir.mkdir(parents=True)
    main_tex = paper_dir / "main.tex"
    main_tex.write_text(
        "\\documentclass{article}\n"
        "\\usepackage{booktabs}\n"
        "\\begin{document}\n"
        "\\input{sections/method}\n"
        "\\end{document}\n",
        encoding="utf-8",
    )
    (sections_dir / "method.tex").write_text(
        "Let $x \\in \\mathbb{R}^d$.\\\\\n"
        "\\toprule\n",
        encoding="utf-8",
    )

    additions = paper_compiler.repair_common_source_dependencies(paper_dir)
    repeated = paper_compiler.repair_common_source_dependencies(paper_dir)
    repaired = main_tex.read_text(encoding="utf-8")

    assert additions == ["amsfonts"]
    assert repeated == []
    assert repaired.count("\\usepackage{amsfonts}") == 1
    assert repaired.count("\\usepackage{booktabs}") == 1


def test_bibtex_sanitizer_repairs_text_fields_without_changing_identifiers() -> None:
    source = r'''% note = {comment_only_value}
@article{sample,
  title = {R&D for EEG_FM with $x_i$ and {Nested_Value}},
  note = "from arxiv_search at \url{https://example.org/a_b}",
  url = {https://example.org/paper_files/a_b?x=1&y=2},
  doi = {10.1000/raw_id},
  eprint = {raw_id},
  author = {Research #1 and Already \& Escaped}
}
'''

    repaired, changes = paper_compiler.sanitize_bibtex_content(source)
    repeated, repeated_changes = paper_compiler.sanitize_bibtex_content(repaired)

    assert "R\\&D for EEG\\_FM" in repaired
    assert "$x_i$" in repaired
    assert "{Nested\\_Value}" in repaired
    assert "from arxiv\\_search" in repaired
    assert r"\url{https://example.org/a_b}" in repaired
    assert "https://example.org/paper_files/a_b?x=1&y=2" in repaired
    assert "10.1000/raw_id" in repaired
    assert "eprint = {raw_id}" in repaired
    assert r"Research \#1 and Already \& Escaped" in repaired
    assert "comment_only_value" in repaired
    assert sum(int(item["escaped_characters"]) for item in changes) == 5
    assert repeated == repaired
    assert repeated_changes == []


def test_compile_repairs_bibliography_before_running_latexmk(
    tmp_path: Path,
    monkeypatch,
) -> None:
    paper_dir = tmp_path / "paper"
    paper_dir.mkdir()
    (paper_dir / "main.tex").write_text(
        r"\documentclass{article}\begin{document}Test\end{document}",
        encoding="utf-8",
    )
    bibliography = paper_dir / "references.bib"
    bibliography.write_text(
        "@misc{x, title={Safe title}, note={from arxiv_search}}\n",
        encoding="utf-8",
    )
    stale_bbl = paper_dir / "main.bbl"
    stale_bbl.write_text("from arxiv_search\n", encoding="utf-8")

    async def fake_run(args, **_kwargs):
        assert "arxiv\\_search" in bibliography.read_text(encoding="utf-8")
        assert not stale_bbl.exists()
        (paper_dir / "main.pdf").write_bytes(b"%PDF-1.4\n%%EOF\n")
        return subprocess.CompletedProcess(args=args, returncode=0, stdout=b"")

    async def fake_page_count(_path: str) -> int:
        return 1

    monkeypatch.setattr(paper_compiler, "_run_command", fake_run)
    monkeypatch.setattr(paper_compiler, "_get_page_count", fake_page_count)

    result = asyncio.run(paper_compiler.compile(str(paper_dir)))

    assert result.success is True
    assert len(result.source_repairs) == 1
    assert result.source_repairs[0]["escaped_characters"] == 1


def test_failed_compile_reads_precise_error_from_final_engine_log(
    tmp_path: Path,
    monkeypatch,
) -> None:
    paper_dir = tmp_path / "paper"
    section_dir = paper_dir / "sections"
    section_dir.mkdir(parents=True)
    (paper_dir / "main.tex").write_text(
        "\\documentclass{article}\n"
        "\\begin{document}\n"
        "\\input{sections/results}\n"
        "\\end{document}\n",
        encoding="utf-8",
    )
    (section_dir / "results.tex").write_text(
        "\\undefinedpreviewguard\n",
        encoding="utf-8",
    )

    async def fake_run(args, **_kwargs):
        (paper_dir / "main.log").write_text(
            "./sections/results.tex:1: Undefined control sequence.\n"
            "l.1 \\undefinedpreviewguard\n",
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(
            args=args,
            returncode=12,
            stdout=b"Latexmk: command failed with exit code 12\n",
        )

    monkeypatch.setattr(paper_compiler, "_run_command", fake_run)

    result = asyncio.run(paper_compiler.compile(str(paper_dir)))

    assert result.success is False
    assert result.errors
    assert result.errors[0].file == "./sections/results.tex"
    assert result.errors[0].line == 1
    assert result.errors[0].message == "Undefined control sequence."
