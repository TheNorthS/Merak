"""Move explicitly planned floats to end matter without editing authored sources."""

import hashlib
import json
import re
from pathlib import Path

from ..utils.atomic_write import atomic_write_json
from .latex_bundle import _bases, _resolve
from .manuscript_text import read_text, write_text_if_changed
from .paper_asset_placement import _FLOAT, _LABEL


RECEIPT = "paper/assembly-layout/PLACEMENT.json"
_INPUT = re.compile(r"\\(?:input|include)\s*\{([^}]+)\}")


def planned_appendix_labels(root: Path) -> set[str]:
    """Only the explicit Placement column can move a currently selected public label."""
    from .paper_asset_reference_contract import selected_publication_references

    selected = {item.label for item in selected_publication_references(root)}
    index, choices = None, {}
    for line in read_text(root / "paper/PAPER_PLAN.md").splitlines():
        if not line.lstrip().startswith("|"):
            index = None
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if any(cell.casefold() == "placement" for cell in cells):
            index = next(i for i, cell in enumerate(cells) if cell.casefold() == "placement")
            continue
        if index is None or len(cells) <= index:
            continue
        labels = set(re.findall(r"(?:fig|tab):[A-Za-z0-9_.:-]+", cells[0])) & selected
        appendix = bool(re.search(r"(?i)\bappendix\b|附录", cells[index]))
        for label in labels:
            if label in choices and choices[label] != appendix:
                raise ValueError(f"Paper plan assigns conflicting placements to {label}")
            choices[label] = appendix
    return {label for label, appendix in choices.items() if appendix}


def _project(root: Path, main: str, labels: set[str]) -> tuple[str, dict[str, str]]:
    paper = root / "paper"
    products, moved, visited, active = {}, {}, {}, set()

    def visit(path: Path, text: str) -> str:
        if path in active:
            raise ValueError("Cyclic LaTeX include in appendix placement")
        if path in visited:
            return visited[path]
        active.add(path)
        def move(match: re.Match[str]) -> str:
            bound = set(_LABEL.findall(match.group())) & labels
            if not bound:
                return match.group()
            if len(bound) != 1:
                raise ValueError("Planned appendix float has ambiguous labels")
            label = next(iter(bound))
            if label in moved:
                raise ValueError(f"Planned appendix float is duplicated: {label}")
            moved[label] = re.sub(r"(\\begin\{(?:figure|table)\*?\})(?:\[[^]]*\])?",
                                  r"\1[!htbp]", match.group(), count=1)
            return ""
        updated = _FLOAT.sub(move, text)
        def include(match: re.Match[str]) -> str:
            source = _resolve(match.group(1), _bases(path, paper, root), root, (".tex", ""))
            if source is None:
                return match.group()
            original = read_text(source)
            derived = visit(source, original)
            if derived == original:
                return match.group()
            relative = "paper/assembly-layout/" + source.relative_to(root).as_posix()
            products[relative] = derived.rstrip() + "\n"
            return "\\input{" + relative.removeprefix("paper/").removesuffix(".tex") + "}"
        updated = _INPUT.sub(include, updated)
        active.remove(path)
        visited[path] = updated
        return updated

    result = visit(paper / "main.tex", main)
    if labels - moved.keys():
        raise ValueError("Planned appendix float is absent from reviewed inputs: " + ", ".join(sorted(labels - moved.keys())))
    appendix = "\n\\clearpage\n\\appendix\n\\section{Supplementary figures and tables}\n\\suppressfloats[t]\n" + "\n\n".join(moved.values()) + "\n"
    if result.count(r"\end{document}") != 1:
        raise ValueError("Appendix placement requires exactly one document end")
    return result.replace(r"\end{document}", appendix + r"\end{document}").rstrip() + "\n", products


def prepare_appendix_assembly(root: Path, main: str) -> str:
    """Compile exact planned float placement while keeping every original byte intact."""
    root = root.resolve()
    labels = planned_appendix_labels(root)
    if not labels:
        return main
    rendered, products = _project(root, main, labels)
    for relative, text in products.items():
        write_text_if_changed(root / relative, text)
    atomic_write_json(root / RECEIPT, {"schema": 1, "original_main": main,
        "plan_sha256": hashlib.sha256((root / "paper/PAPER_PLAN.md").read_bytes()).hexdigest(),
        "labels": sorted(labels), "rendered_main_sha256": hashlib.sha256(rendered.encode()).hexdigest()})
    return rendered


def original_assembly_inputs(root: Path) -> set[str]:
    """Recompute exact placement and overlays before accepting original section identities."""
    root = root.resolve()
    record = json.loads((root / RECEIPT).read_text(encoding="utf-8"))
    if (record.get("schema") != 1 or not isinstance(record.get("original_main"), str)
            or record.get("plan_sha256") != hashlib.sha256((root / "paper/PAPER_PLAN.md").read_bytes()).hexdigest()):
        raise ValueError("Appendix placement proof is invalid or bound to a stale plan")
    labels = planned_appendix_labels(root)
    if sorted(labels) != record.get("labels"):
        raise ValueError("Appendix placement does not match the selected scientific labels")
    rendered, products = _project(root, record["original_main"], labels)
    from .paper_print_projection import assembled_print_sha256

    digest = hashlib.sha256(rendered.encode()).hexdigest()
    if digest != record.get("rendered_main_sha256") or digest != assembled_print_sha256(root):
        raise ValueError("Appendix placement main document is stale or edited")
    if any(read_text(root / relative) != text for relative, text in products.items()):
        raise ValueError("Appendix placement overlay differs from its reviewed source")
    return set(_INPUT.findall(record["original_main"]))
