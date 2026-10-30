from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import json

from server.services.paper_section_review import _required_preview_labels


def test_optional_paired_reversal_label_is_required_only_when_rendered(
    tmp_path: Path,
) -> None:
    table_dir = tmp_path / "paper" / "tables"
    table_dir.mkdir(parents=True)
    section_path = tmp_path / "paper" / "sections" / "05_results.tex"
    section_path.parent.mkdir()
    section_text = "\\section{Results}\n\\input{tables/synthetic_preview_results}\n"
    section_path.write_text(section_text, encoding="utf-8")
    context = SimpleNamespace(
        root=tmp_path,
        path=section_path,
        text=section_text,
        issues=[],
        policy=SimpleNamespace(
            preview_figure_labels=("fig:main",),
            preview_table_labels=("tab:main", "tab:paired-reversals"),
        ),
    )

    assert _required_preview_labels(context) == set()

    (table_dir / "synthetic_preview_results.tex").write_text(
        r"\begin{table}\caption{Paired comparisons}\label{tab:paired-reversals}\end{table}",
        encoding="utf-8",
    )
    (table_dir / "TABLE_MANIFEST.json").write_text(json.dumps({"schema": 3, "tables": [{
        "id": "paired", "label": "tab:paired-reversals", "scientific_role": "result",
        "latex_path": "paper/tables/synthetic_preview_results.tex",
    }]}), encoding="utf-8")

    assert _required_preview_labels(context) == {
        "tab:paired-reversals",
    }
