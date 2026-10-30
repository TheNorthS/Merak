"""Give reviewers the actual reachable input graph and validated projection lineage."""

from pathlib import Path
import re

from .latex_bundle import _reachable_sources, _tex_text


def consistency_source_inventory(root: Path) -> str:
    root = root.resolve()
    main = root / "paper/main.tex"
    if not main.is_file():
        return ""
    labels = {}
    sources = _reachable_sources(main, root / "paper", root)
    for path in sorted(sources):
        relative = path.relative_to(root).as_posix()
        for label in re.findall(r"\\label\s*\{([^}]+)\}", _tex_text(path)):
            labels.setdefault(label, []).append(relative)
    lines = ["\n## Runtime-verified assembled input inventory",
        "Only files reachable from main.tex are compiled. Original authored files and exact derived copies "
        "are provenance pairs, not two independent manuscript copies. Read canonical originals for scientific "
        "content and the listed actual inputs for inclusion/label questions. Never count unreachable originals "
        "as additional floats or label definitions."]
    if (root / "paper/assembly-layout/PLACEMENT.json").is_file():
        from .paper_appendix_assembly import original_assembly_inputs
        original_assembly_inputs(root)
        lines.append("The appendix projection was recomputed from current authors, plan and selected floats; "
                     "its main document and every overlay matched exactly. Assembly-layout files are runtime-owned; "
                     "scientific prose repairs belong to the corresponding paper/sections file.")
    lines.append("Actual reachable inputs:\n" + "\n".join(f"- {path.relative_to(root).as_posix()}" for path in sorted(sources)))
    lines.append("Actual label definitions (duplicates are explicitly listed):\n" + "\n".join(
        f"- {label}: {len(paths)} definition(s), {', '.join(paths)}" for label, paths in sorted(labels.items())))
    lines.extend(_visible_float_captions(root, sources))
    return "\n".join(lines)


def _visible_float_captions(root: Path, sources: set[Path]) -> list[str]:
    """Supply exact current caption commands; comments and unreachable archives are not visible text."""
    from .paper_table_source_labels import _caption
    from .simulation_policy import strip_latex_comments

    lines = ["\n## Current reachable figure/table captions (LaTeX comments removed)",
        "These are caption commands from the current compiled input graph, not visual proof of rendered layout. "
        "LaTeX comments beginning with an unescaped % (including MERAK_PRIMARY_MATRIX_CAPTION provenance) "
        "are not rendered. Do not call comment values, manifest descriptions or unreachable older projections "
        "visible captions. For a caption defect quote the exact current caption and its source/label; "
        "inspect the actual PDF for visual claims. Reconsider earlier review findings against these current inputs."]
    for path in sorted(sources):
        text = strip_latex_comments(_tex_text(path))
        for block in re.findall(r"\\begin\{(?:figure|table)\*?\}.*?\\end\{(?:figure|table)\*?\}", text, re.DOTALL):
            labels = re.findall(r"\\label\s*\{([^}]+)\}", block)
            try:
                caption = _caption(block)
            except ValueError as error:
                caption = f"INVALID CAPTION: {error}"
            lines.append(f"- {path.relative_to(root).as_posix()} [{', '.join(labels)}]: {caption}")
    return lines
