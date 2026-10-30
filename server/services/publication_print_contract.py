"""Read source-bound publication placement widths in PDF big points (bp).

Static resolution accepts explicit current template dimensions only. Unknown
macros, conditional width assignments and constrained inner layouts require a
controlled TeX measurement rather than a guessed canvas width or DPI rule.
This module is read-only and never runs TeX or mutates publication artifacts.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .latex_bundle import GRAPHIC_EXTENSIONS, _bases, _resolve, _tex_text


class UnresolvedPublicationPrintContract(ValueError):
    """The template needs an explicitly authorized controlled TeX measurement."""


@dataclass(frozen=True)
class PublicationPrintContract:
    text_width_bp: float
    column_width_bp: float
    template_source_sha256: dict[str, str]
    placements: tuple[dict[str, Any], ...]
    minimum_font_bp: float = 8.0
    target_font_bp: float = 8.5

    def to_dict(self) -> dict[str, Any]:
        payload = {"schema": 1, "unit": "PDF bp (1/72 inch)", "text_width_bp": self.text_width_bp,
                   "column_width_bp": self.column_width_bp, "minimum_font_bp": self.minimum_font_bp,
                   "target_font_bp": self.target_font_bp, "template_source_sha256": dict(self.template_source_sha256),
                   "placements": [dict(item) for item in self.placements]}
        payload["contract_sha256"] = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        return payload


_LITERAL = re.compile(r"^([+-]?(?:\d+(?:\.\d*)?|\.\d+))\s*(?:true\s*)?(bp|pt|in|cm|mm|pc|sp)$")
_DIMENSIONS = ("textwidth", "columnwidth", "columnsep", "paperwidth")
_DEPENDENCY = re.compile(r"\\(documentclass|usepackage|RequirePackage|input|include|subfile|LoadClass)"
                         r"(?:\s*\[[^]]*\])?\s*\{([^}]+)\}")
_GRAPHIC = re.compile(r"\\includegraphics\*?(?:\s*\[([^]]*)\])?\s*\{([^}]+)\}")
_ENVIRONMENT = re.compile(r"\\(begin|end)\s*\{([^}]+)\}")


def _dimension_bp(value: str) -> float:
    match = _LITERAL.fullmatch(" ".join(value.strip().split()))
    if match is None:
        raise UnresolvedPublicationPrintContract("Dynamic TeX dimension requires controlled measurement: " + value)
    factor = {"bp": 1.0, "pt": 72 / 72.27, "in": 72.0, "cm": 72 / 2.54,
              "mm": 72 / 25.4, "pc": 12 * 72 / 72.27, "sp": 72 / 72.27 / 65536}[match[2]]
    return float(match[1]) * factor


def _expand_sources(entry: Path, paper: Path, root: Path) -> tuple[list[tuple[Path, str, tuple[str, ...]]], str]:
    """Keep declared execution order and source identities without expanding macros."""
    sources: list[tuple[Path, str, tuple[str, ...]]] = []
    active: set[Path] = set()

    def visit(path: Path, inherited: tuple[str, ...] = ()) -> str:
        path = path.resolve()
        if path in active:
            raise UnresolvedPublicationPrintContract("Recursive TeX source import requires measurement")
        if not path.is_relative_to(root):
            raise UnresolvedPublicationPrintContract("Template source leaves its project")
        active.add(path)
        text = _tex_text(path)
        sources.append((path, text, inherited))
        result, cursor = [], 0
        for match in _DEPENDENCY.finditer(text):
            result.append(text[cursor:match.end()])
            command, names = match.groups()
            suffix = ".tex" if command in {"input", "include", "subfile"} else ".cls" if command in {"documentclass", "LoadClass"} else ".sty"
            for name in names.split(","):
                context_path = paper / path.name if path == entry else path
                dependency = _resolve(name, _bases(context_path, paper, root), root, (suffix, ""))
                if dependency:
                    if suffix == ".tex" and (_conditional_depth(text[:match.start()]) or _brace_depth(text[:match.start()])):
                        raise UnresolvedPublicationPrintContract("Conditional or macro-based source import requires controlled measurement")
                    context = tuple(_environment_stack(text[:match.start()], inherited)) if suffix == ".tex" else ()
                    result.append(visit(dependency, context))
                elif suffix == ".tex":
                    raise UnresolvedPublicationPrintContract("Reachable manuscript source cannot be resolved: " + name)
            cursor = match.end()
        result.append(text[cursor:])
        active.remove(path)
        return "\n".join(result)

    expanded = visit(entry)
    return sources, expanded


def _width_assignments(text: str) -> dict[str, float]:
    names = "|".join(_DIMENSIONS)
    pattern = re.compile(r"\\(setlength|addtolength)\s*\{\\(" + names + r")\}\s*\{([^}]+)\}"
                         r"|\\(" + names + r")\b\s*=\s*([^\n{}%]+)"
                         r"|\\(" + names + r")\b\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+)\s*(?:true\s*)?(?:bp|pt|in|cm|mm|pc|sp))")
    dimensions = {}
    for match in pattern.finditer(text):
        operation, name, value, direct, direct_value, plain, plain_value = match.groups()
        name, value = name or direct or plain, value or direct_value or plain_value
        # Relevant assignments inside unresolved conditionals cannot be assumed.
        prefix = text[:match.start()]
        if _conditional_depth(prefix) or _brace_depth(prefix) or r"\begin{document}" in prefix:
            raise UnresolvedPublicationPrintContract("Conditional template width requires controlled TeX measurement")
        parsed = _dimension_bp(value)
        if operation == "addtolength":
            if name not in dimensions:
                raise UnresolvedPublicationPrintContract("Relative template width has no declared initial value")
            parsed += dimensions[name]
        if parsed <= 0:
            raise UnresolvedPublicationPrintContract("Publication width must be positive")
        dimensions[name] = parsed
    return dimensions


def _conditional_depth(text: str) -> int:
    depth = 0
    for match in re.finditer(r"\\(?:if[a-zA-Z@]*|fi)\b", text):
        if match.group() == r"\fi":
            depth = max(0, depth - 1)
        elif not re.search(r"\\newif\s*$", text[:match.start()]):
            depth += 1
    return depth


def _brace_depth(text: str) -> int:
    depth = 0
    for match in re.finditer(r"(?<!\\)[{}]", text):
        depth = max(0, depth + (1 if match.group() == "{" else -1))
    return depth


def _paper_widths(expanded: str) -> tuple[float, float]:
    if re.search(r"\\(?:advance|multiply|divide)\s*\\(?:textwidth|columnwidth|columnsep)\b"
                 r"|\\(?:textwidth|columnwidth|columnsep)\s*\\(?:dimexpr|paperwidth|textwidth|columnwidth)\b"
                 r"|\\mag\s*=?\s*(?!1000\b)\d+", expanded):
        raise UnresolvedPublicationPrintContract("Dynamic width arithmetic or magnification requires controlled measurement")
    dimensions = _width_assignments(expanded)
    geometry = re.findall(r"\\(?:usepackage|RequirePackage)\s*\[([^]]+)\]\s*\{geometry\}|\\geometry\s*\{([^}]+)\}", expanded)
    if geometry and "textwidth" in dimensions:
        raise UnresolvedPublicationPrintContract("Mixed geometry and width overrides require controlled measurement")
    for option, command in geometry:
        values = dict(part.strip().split("=", 1) for part in (option or command).split(",") if "=" in part)
        if "textwidth" in values:
            dimensions["textwidth"] = _dimension_bp(values["textwidth"])
        elif "margin" in values or "left" in values or "right" in values:
            if "paperwidth" in values:
                paper = _dimension_bp(values["paperwidth"])
            else:
                declaration = re.search(r"\\documentclass\s*\[([^]]*)\]", expanded)
                options = declaration[1] if declaration else ""
                paper = 612.0 if "letterpaper" in options else 210 * 72 / 25.4 if "a4paper" in options else dimensions.get("paperwidth")
            if paper is None or not ("margin" in values or {"left", "right"} <= set(values)):
                raise UnresolvedPublicationPrintContract("Geometry margins have no explicit paper width or both side margins")
            dimensions["textwidth"] = paper - _dimension_bp(values.get("left", values.get("margin", ""))) - _dimension_bp(values.get("right", values.get("margin", "")))
        if "columnsep" in values:
            dimensions["columnsep"] = _dimension_bp(values["columnsep"])
    text = dimensions.get("textwidth")
    if text is None:
        raise UnresolvedPublicationPrintContract("Actual reachable template does not declare text width")
    classes = re.findall(r"\\documentclass(?:\[([^]]*)\])?", expanded)
    two_columns = any("twocolumn" in options for options in classes) or bool(re.search(r"\\twocolumn\b", expanded))
    column = dimensions.get("columnwidth")
    if any(_conditional_depth(expanded[:match.start()]) or _brace_depth(expanded[:match.start()])
           for match in re.finditer(r"\\(?:twocolumn|onecolumn)\b", expanded)):
        raise UnresolvedPublicationPrintContract("Conditional column mode requires controlled measurement")
    if column is None:
        class_names = re.findall(r"\\documentclass(?:\[[^]]*\])?\s*\{([^}]+)\}", expanded)
        explicit_mode = any("onecolumn" in options or "twocolumn" in options for options in classes)
        if not explicit_mode and not re.search(r"\\(?:onecolumn|twocolumn)\b", expanded) and any(
            name not in {"article", "report", "book", "minimal"} for name in class_names
        ):
            raise UnresolvedPublicationPrintContract("Unknown class column mode requires controlled measurement")
        if two_columns and "columnsep" not in dimensions:
            raise UnresolvedPublicationPrintContract("Two-column template has no declared column separation")
        column = (text - dimensions["columnsep"]) / 2 if two_columns else text
    if not 0 < column <= text:
        raise UnresolvedPublicationPrintContract("Publication column width is invalid")
    return text, column


def _placement_width(options: str, text: float, column: float, environments: list[str]) -> tuple[float, str]:
    values = dict(part.strip().split("=", 1) for part in options.split(",") if "=" in part)
    if (any(name in environments for name in ("minipage", "subfigure", "subfloat", "wrapfigure", "figurebox"))
            or set(values) - {"width"} or "width" not in values):
        raise UnresolvedPublicationPrintContract("Constrained/inner graphic placement requires controlled measurement")
    expression = values["width"].strip()
    match = re.fullmatch(r"([0-9]*(?:\.[0-9]+)?)\s*\\(textwidth|columnwidth|linewidth)", expression)
    if match:
        fraction = float(match[1] or 1)
        base = text if match[2] == "textwidth" or match[2] == "linewidth" and "figure*" in environments else column
        width = fraction * base
    else:
        width = _dimension_bp(expression)
    if not 0 < width <= text:
        raise UnresolvedPublicationPrintContract("Graphic width exceeds the actual page text region")
    return width, expression


def _environment_stack(text: str, inherited: tuple[str, ...] = ()) -> list[str]:
    stack = list(inherited)
    for action, environment in _ENVIRONMENT.findall(text):
        if action == "begin":
            stack.append(environment)
        elif stack and stack[-1] == environment:
            stack.pop()
    return stack


def _placements(sources: list[tuple[Path, str, tuple[str, ...]]], root: Path, paper: Path,
                text: float, column: float, selected: Path | None) -> tuple[dict[str, Any], ...]:
    graphics = []
    for path, content, inherited in sources:
        context_path = paper / path.name if path == sources[0][0] else path
        directories = []
        for _source, context, _inherited in sources:
            for block in re.findall(r"\\graphicspath\s*\{((?:\{[^}]*\}\s*)+)\}", context):
                directories.extend((base / raw).resolve() for raw in re.findall(r"\{([^}]*)\}", block)
                                   for base in (paper, context_path.parent))
        for match in _GRAPHIC.finditer(content):
            options, raw = match.groups()
            graphic = _resolve(raw, [*_bases(context_path, paper, root), *directories], root, GRAPHIC_EXTENSIONS)
            if graphic is None:
                raise UnresolvedPublicationPrintContract("Graphic placement has no canonical project-local artifact: " + raw)
            if selected is not None and graphic != selected:
                continue
            if _brace_depth(content[:match.start()]) or _conditional_depth(content[:match.start()]):
                raise UnresolvedPublicationPrintContract("Graphic placement inside an unresolved macro or conditional requires measurement")
            stack = _environment_stack(content[:match.start()], inherited)
            width, expression = _placement_width(options or "", text, column, stack)
            graphics.append({"graphic_relative": graphic.relative_to(root).as_posix(), "width_bp": width,
                             "width_expression": expression, "source_relative": path.relative_to(root).as_posix(),
                             "line": content[:match.start()].count("\n") + 1,
                             "graphic_sha256": hashlib.sha256(graphic.read_bytes()).hexdigest()})
    if not graphics:
        raise UnresolvedPublicationPrintContract("No actual graphic placement exists for the requested asset")
    return tuple(graphics)


def _entry_source_root(root: Path, entry: Path) -> Path:
    """Only the exact active, hash-proven main archive retains paper's source root."""
    archive = root / "paper/derived-figures/ORIGINAL_MAIN.tex"
    if entry.name != archive.name:
        return entry.parent
    if entry != archive:
        raise UnresolvedPublicationPrintContract("Original print archive is not the canonical project entrypoint")
    from .paper_derived_figure_binding import _original_print_entrypoint

    try:
        verified = _original_print_entrypoint(root)
    except (OSError, UnicodeError, ValueError, TypeError, KeyError) as error:
        raise UnresolvedPublicationPrintContract("Original print archive lacks its exact active projection binding") from error
    if verified != entry:
        raise UnresolvedPublicationPrintContract("Original print archive is not an active verified manuscript entrypoint")
    return root / "paper"


def read_publication_print_contract(project_root: Path, main_tex: Path | None = None,
                                    graphic_path: Path | None = None) -> PublicationPrintContract:
    """Read actual template and placement identities; never invoke a compiler."""
    root = project_root.resolve()
    entry = (main_tex if main_tex is not None else root / "paper/main.tex").resolve()
    if not entry.is_relative_to(root) or not entry.is_file():
        raise UnresolvedPublicationPrintContract("Publication entrypoint is missing or outside its project")
    selected = (root / graphic_path).resolve() if graphic_path is not None else None
    if selected is not None and not selected.is_relative_to(root):
        raise UnresolvedPublicationPrintContract("Requested graphic leaves its project")
    paper = _entry_source_root(root, entry)
    sources, expanded = _expand_sources(entry, paper, root)
    text, column = _paper_widths(expanded)
    signatures = {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path, _, _inherited in sources}
    placements = _placements(sources, root, paper, text, column, selected)
    return PublicationPrintContract(text, column, signatures, placements)
