"""Venue metadata and LaTeX scaffold generation."""

from __future__ import annotations

from pathlib import Path

from ..utils.atomic_write import atomic_write_text


# 会议模板
VENUE_TEMPLATES = {
    "neurips": {
        "name": "NeurIPS 2026",
        "style": "neurips_2026",
        "page_limit": 9,
        "columns": 1,
    },
    "iclr": {
        "name": "ICLR 2027",
        "style": "iclr2027_conference",
        "page_limit": 9,
        "columns": 1,
    },
    "cvpr": {
        "name": "CVPR 2026",
        "style": "cvpr",
        "page_limit": 8,
        "columns": 2,
    },
    "acl": {
        "name": "ACL 2026",
        "style": "acl",
        "page_limit": 8,
        "columns": 2,
    },
    "aaai": {
        "name": "AAAI 2027",
        "style": "aaai",
        "page_limit": 7,
        "columns": 2,
    },
    "acm_mm": {
        "name": "ACM Multimedia",
        "style": "acmart",
        "page_limit": 9,
        "columns": 2,
    },
    "ieee": {
        "name": "IEEE Conference",
        "style": "IEEEtran",
        "page_limit": 8,
        "columns": 2,
    },
}


# ==================== Venue Template Scaffolding ====================

VENUE_MAIN_TEX = {
    "neurips": r"""\documentclass{{article}}
\usepackage[preprint]{{neurips_2026}}
\usepackage{{amsmath,amssymb,amsfonts}}
\usepackage{{graphicx}}
\usepackage{{hyperref}}
\usepackage{{booktabs}}

% figures/ is a sibling of paper/ — paths are relative to this file's directory
\graphicspath{{{{../figures/plots/}}{{../figures/diagrams/}}{{../figures/assets/}}}}

\title{{{title}}}

\author{{
  {author} \\
  {affiliation} \\
  \texttt{{{email}}}
}}

\begin{{document}}
\maketitle

\begin{{abstract}}
{abstract}
\end{{abstract}}

\section{{Introduction}}

\section{{Related Work}}

\section{{Method}}

\section{{Experiments}}

\section{{Conclusion}}

\bibliographystyle{{plain}}
\bibliography{{references}}

\end{{document}}
""",
    "iclr": r"""\documentclass{{article}}
\usepackage{{iclr2027_conference,times}}
\usepackage{{amsmath,amssymb}}
\usepackage{{graphicx}}
\usepackage{{hyperref}}
\usepackage{{booktabs}}

\graphicspath{{{{../figures/plots/}}{{../figures/diagrams/}}{{../figures/assets/}}}}

\title{{{title}}}

\author{{
  {author} \\
  {affiliation} \\
  \texttt{{{email}}}
}}

\iclrfinalcopy

\begin{{document}}
\maketitle

\begin{{abstract}}
{abstract}
\end{{abstract}}

\section{{Introduction}}

\section{{Related Work}}

\section{{Method}}

\section{{Experiments}}

\section{{Conclusion}}

\bibliography{{references}}
\bibliographystyle{{iclr2027_conference}}

\end{{document}}
""",
    "cvpr": r"""\documentclass[10pt,twocolumn,letterpaper]{{article}}
\usepackage{{cvpr}}
\usepackage{{amsmath,amssymb}}
\usepackage{{graphicx}}
\usepackage{{hyperref}}
\usepackage{{booktabs}}

\graphicspath{{{{../figures/plots/}}{{../figures/diagrams/}}{{../figures/assets/}}}}

\def\cvprPaperID{{****}}
\def\confName{{CVPR}}
\def\confYear{{2026}}

\title{{{title}}}

\author{{
  {author} \\
  {affiliation} \\
  \texttt{{{email}}}
}}

\begin{{document}}
\maketitle

\begin{{abstract}}
{abstract}
\end{{abstract}}

\section{{Introduction}}

\section{{Related Work}}

\section{{Method}}

\section{{Experiments}}

\section{{Conclusion}}

{{\small
\bibliographystyle{{ieee_fullname}}
\bibliography{{references}}
}}

\end{{document}}
""",
    "acl": r"""\documentclass[11pt]{{article}}
\usepackage{{acl}}
\usepackage{{amsmath,amssymb}}
\usepackage{{graphicx}}
\usepackage{{hyperref}}
\usepackage{{booktabs}}

\graphicspath{{{{../figures/plots/}}{{../figures/diagrams/}}{{../figures/assets/}}}}

\title{{{title}}}

\author{{
  {author} \\
  {affiliation} \\
  \texttt{{{email}}}
}}

\begin{{document}}
\maketitle

\begin{{abstract}}
{abstract}
\end{{abstract}}

\section{{Introduction}}

\section{{Related Work}}

\section{{Method}}

\section{{Experiments}}

\section{{Conclusion}}

\bibliography{{references}}

\end{{document}}
""",
    "aaai": r"""\documentclass[letterpaper]{{article}}
\usepackage{{aaai}}
\usepackage{{times}}
\usepackage{{helvet}}
\usepackage{{courier}}
\usepackage{{graphicx}}
\usepackage{{amsmath,amssymb}}
\usepackage{{booktabs}}

\graphicspath{{{{../figures/plots/}}{{../figures/diagrams/}}{{../figures/assets/}}}}

\setlength{{\pdfpagewidth}}{{8.5in}}
\setlength{{\pdfpageheight}}{{11in}}

\title{{{title}}}
\author{{
  {author} \\
  {affiliation} \\
  {email}
}}

\begin{{document}}
\maketitle

\begin{{abstract}}
{abstract}
\end{{abstract}}

\section{{Introduction}}

\section{{Related Work}}

\section{{Method}}

\section{{Experiments}}

\section{{Conclusion}}

\bibliography{{references}}
\bibliographystyle{{aaai}}

\end{{document}}
""",
    "acm_mm": r"""\documentclass[sigconf]{{acmart}}
\usepackage{{graphicx}}
\usepackage{{booktabs}}

\graphicspath{{{{../figures/plots/}}{{../figures/diagrams/}}{{../figures/assets/}}}}

\title{{{title}}}

\author{{{author}}}
\affiliation{{%
  \institution{{{affiliation}}}
}}
\email{{{email}}}

\begin{{document}}
\maketitle

\begin{{abstract}}
{abstract}
\end{{abstract}}

\keywords{{keyword1, keyword2, keyword3}}

\section{{Introduction}}

\section{{Related Work}}

\section{{Method}}

\section{{Experiments}}

\section{{Conclusion}}

\bibliographystyle{{ACM-Reference-Format}}
\bibliography{{references}}

\end{{document}}
""",
    "ieee": r"""\documentclass[conference]{{IEEEtran}}
\usepackage{{amsmath,amssymb}}
\usepackage{{graphicx}}
\usepackage{{hyperref}}
\usepackage{{booktabs}}
\usepackage{{cite}}

\graphicspath{{{{../figures/plots/}}{{../figures/diagrams/}}{{../figures/assets/}}}}

\title{{{title}}}

\author{{
  \IEEEauthorblockN{{{author}}}
  \IEEEauthorblockA{{{affiliation} \\
  {email}}}
}}

\begin{{document}}
\maketitle

\begin{{abstract}}
{abstract}
\end{{abstract}}

\begin{{IEEEkeywords}}
keyword1, keyword2, keyword3
\end{{IEEEkeywords}}

\section{{Introduction}}

\section{{Related Work}}

\section{{Proposed Method}}

\section{{Experiments}}

\section{{Conclusion}}

\bibliographystyle{{IEEEtran}}
\bibliography{{references}}

\end{{document}}
""",
}


def _ensure_support_files(project_path: Path) -> list[str]:
    created: list[str] = []
    bib_path = project_path / "references.bib"
    if not bib_path.exists():
        atomic_write_text(bib_path, "% Add your references here\n")
        created.append("references.bib")
    latexmkrc = project_path / ".latexmkrc"
    if not latexmkrc.exists():
        atomic_write_text(
            latexmkrc,
            "# Latexmk configuration\n$pdf_mode = 1;\n"
            "$pdflatex = 'pdflatex -interaction=nonstopmode -halt-on-error %O %S';\n",
        )
        created.append(".latexmkrc")
    gitignore = project_path / ".gitignore"
    if not gitignore.exists():
        atomic_write_text(
            gitignore,
            "# LaTeX auxiliary files\n*.aux\n*.bbl\n*.blg\n*.fdb_latexmk\n"
            "*.fls\n*.log\n*.out\n*.toc\n*.synctex.gz\n*.pdf\n",
        )
        created.append(".gitignore")
    return created


def scaffold_paper_files(
    project_dir: str,
    venue: str,
    title: str = "Your Paper Title",
    author: str = "Author Name",
    affiliation: str = "University",
    email: str = "author@example.com",
    abstract: str = "Your abstract here.",
    *,
    overwrite_main: bool = True,
) -> dict:
    """Synchronously create a venue paper scaffold.

    The project scaffold service is synchronous and is called from FastAPI
    request handlers that already own an event loop.  Keeping the filesystem
    implementation synchronous avoids nested event loops while the async
    public wrapper below remains compatible with the paper API and tools.

    Returns:
        {"success": bool, "files_created": list[str], "message": str}
    """
    if venue not in VENUE_MAIN_TEX:
        return {"success": False, "files_created": [], "message": f"Unknown venue: {venue}. Available: {list(VENUE_MAIN_TEX.keys())}"}

    project_path = Path(project_dir)
    project_path.mkdir(parents=True, exist_ok=True)

    files_created = []

    # 1. 生成 main.tex
    template = VENUE_MAIN_TEX[venue]
    main_content = template.format(
        title=title,
        author=author,
        affiliation=affiliation,
        email=email,
        abstract=abstract,
    )
    main_path = project_path / "main.tex"
    if overwrite_main or not main_path.exists():
        atomic_write_text(main_path, main_content)
        files_created.append("main.tex")

    files_created.extend(_ensure_support_files(project_path))

    venue_info = VENUE_TEMPLATES[venue]
    return {
        "success": True,
        "files_created": files_created,
        "message": f"Paper scaffolded for {venue_info['name']} (page limit: {venue_info['page_limit']}, columns: {venue_info['columns']})",
        "venue_info": venue_info,
    }


async def scaffold_paper(
    project_dir: str,
    venue: str,
    title: str = "Your Paper Title",
    author: str = "Author Name",
    affiliation: str = "University",
    email: str = "author@example.com",
    abstract: str = "Your abstract here.",
) -> dict:
    """Async-compatible wrapper used by the API and agent tool surface."""

    return scaffold_paper_files(
        project_dir=project_dir,
        venue=venue,
        title=title,
        author=author,
        affiliation=affiliation,
        email=email,
        abstract=abstract,
    )


