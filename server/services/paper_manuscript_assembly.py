"""Deterministic assembly of reviewed paper sections into main.tex."""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any, Callable, Iterable

from .manuscript_text import (
    latex_text,
    read_json,
    read_owned_state,
    read_text,
    write_json,
    write_text_if_changed,
)


def assemble_manuscript(
    *,
    paths: dict[str, Path],
    specs: Iterable[Any],
    venue_bundles: dict[str, dict[str, Any]],
    family_bundles: dict[str, dict[str, Any]],
    content_markers: tuple[str, ...],
    disclosure_title: str,
    disclosure_text: str,
    canonical_venue: Callable[[Any], str],
    canonical_family: Callable[[str, dict[str, Any]], str],
    install_venue: Callable[[Path, str], dict[str, Any]],
    install_custom: Callable[[Path, str], tuple[dict[str, Any], str, str]],
    error_factory: Callable[[str, list[str]], Exception],
) -> Path:
    evidence = dict(read_json(paths["contracts"]).get("evidence") or {})
    title = " ".join(read_text(paths["title"]).split())
    if not title:
        raise error_factory("assembly", ["paper/TITLE.txt is missing"])
    sections = _section_files(paths, specs)
    missing = [str(path) for _, path in sections if not path.is_file() or path.stat().st_size == 0]
    if missing:
        raise error_factory("assembly", ["missing section files: " + ", ".join(missing)])
    _normalize_section_paths(paths, sections)
    body = title + "".join(read_text(path) for _, path in sections)
    unicode_package = "\\usepackage[UTF8,scheme=plain]{ctex}\n" if any(ord(char) > 127 for char in body) else ""
    style = read_json(paths["style"])
    state = read_owned_state(paths["state"])
    template = _resolve_template(
        paths, style, state, venue_bundles, family_bundles,
        canonical_venue, canonical_family, install_venue, install_custom,
    )
    bibliography = _bibliography(paths, template["bibliography_style"])
    disclosure = _disclosure(evidence, disclosure_title, disclosure_text)
    inputs = _manuscript_inputs(paths, sections)
    main = _render_main(
        title, inputs, bibliography, disclosure, unicode_package,
        template, content_markers, error_factory,
    )
    from .paper_appendix_assembly import prepare_appendix_assembly
    main = prepare_appendix_assembly(paths["root"], main)
    write_text_if_changed(paths["main"], main)
    _persist_template_resolution(paths, state, style, template["metadata"])
    return paths["main"]


def _section_files(paths: dict[str, Path], specs: Iterable[Any]) -> list[tuple[str, Path]]:
    return [
        ("00_abstract", paths["sections"] / "00_abstract.tex"),
        *((Path(spec.filename).stem, paths["sections"] / spec.filename) for spec in specs),
    ]


def _normalize_section_paths(
    paths: dict[str, Path], sections: list[tuple[str, Path]]
) -> None:
    graphic_pattern = re.compile(
        r"(\\includegraphics(?:\s*\[[^\]]*\])?\s*\{)([^{}]+)(\})"
    )
    input_pattern = re.compile(r"(\\(?:input|include)\s*\{)([^{}]+)(\})")
    for _, section_path in sections:
        text = read_text(section_path)
        text = graphic_pattern.sub(
            lambda match: _canonical_graphic(paths, match), text
        )
        text = input_pattern.sub(
            lambda match: _canonical_input(paths, match), text
        )
        write_text_if_changed(section_path, text)


def _canonical_graphic(paths: dict[str, Path], match: re.Match[str]) -> str:
    raw = match.group(2).strip().replace("\\", "/")
    normalized = raw[2:] if raw.startswith("./") else raw
    if not normalized.startswith("figures/"):
        return match.group(0)
    candidate = paths["root"] / Path(normalized)
    paper_candidate = paths["paper"] / Path(normalized)
    if paper_candidate.is_file() or not candidate.is_file() or candidate.stat().st_size <= 0:
        return match.group(0)
    return match.group(1) + "../" + normalized + match.group(3)


def _canonical_input(paths: dict[str, Path], match: re.Match[str]) -> str:
    raw = match.group(2).strip().replace("\\", "/")
    normalized = raw[2:] if raw.startswith("./") else raw
    if not normalized.startswith("paper/"):
        return match.group(0)
    relative = normalized[len("paper/"):]
    suffix = "" if Path(relative).suffix else ".tex"
    candidate = paths["paper"] / (relative + suffix)
    duplicate = paths["paper"] / (normalized + suffix)
    if duplicate.is_file() or not candidate.is_file() or candidate.stat().st_size <= 0:
        return match.group(0)
    return match.group(1) + relative + match.group(3)


def _resolve_template(
    paths: dict[str, Path], style: dict[str, Any], state: dict[str, Any],
    venue_bundles: dict[str, dict[str, Any]], family_bundles: dict[str, dict[str, Any]],
    canonical_venue: Callable[[Any], str],
    canonical_family: Callable[[str, dict[str, Any]], str],
    install_venue: Callable[[Path, str], dict[str, Any]],
    install_custom: Callable[[Path, str], tuple[dict[str, Any], str, str]],
) -> dict[str, Any]:
    requested_venue = str(style.get("target_venue") or state.get("target_venue") or "")
    requested_template = str(
        style.get("venue_template_path") or state.get("venue_template_path")
        or dict(state.get("authoring_options") or {}).get("venue_template_path") or ""
    ).strip()
    publication_style = dict(style.get("publication_visual_style") or {})
    if requested_template:
        metadata, custom_text, documentclass = install_custom(paths["paper"], requested_template)
        match = re.search(r"\\bibliographystyle\{([^}]+)\}", custom_text)
        return _template_config(
            metadata, documentclass, "", match.group(1).strip() if match else "plain",
            "standard", False, "", False, custom_text,
        )
    venue_key = canonical_venue(requested_venue)
    if venue_key:
        bundle = venue_bundles[venue_key]
        return _bundle_config(install_venue(paths["paper"], venue_key), bundle)
    family_key = canonical_family(requested_venue, publication_style)
    bundle = family_bundles[family_key]
    metadata = {
        "key": family_key, "label": str(bundle["label"]),
        "mode": "venue_family_policy", "official_assets_bundled": False,
        "assets": [], "requested_venue": requested_venue or "unspecified",
        "research_family": str(publication_style.get("family") or ""),
    }
    return _bundle_config(metadata, bundle)


def _template_config(
    metadata: dict[str, Any], documentclass: str, venue_preamble: str,
    bibliography_style: str, title_mode: str, hyperref: bool, geometry: str,
    abstract_before_title: bool, custom_text: str = "",
) -> dict[str, Any]:
    return {
        "metadata": metadata, "documentclass": documentclass,
        "venue_preamble": venue_preamble, "bibliography_style": bibliography_style,
        "title_mode": title_mode, "hyperref": hyperref, "geometry": geometry,
        "abstract_before_title": abstract_before_title, "custom_text": custom_text,
    }


def _bundle_config(metadata: dict[str, Any], bundle: dict[str, Any]) -> dict[str, Any]:
    return _template_config(
        metadata, str(bundle["documentclass"]), str(bundle["venue_preamble"]),
        str(bundle["bibliography_style"]), str(bundle["title_mode"]),
        bool(bundle["hyperref"]), str(bundle.get("geometry") or ""),
        bool(bundle.get("abstract_before_title", False)),
    )


def _bibliography(paths: dict[str, Path], style: str) -> str:
    if not (paths["paper"] / "references.bib").is_file():
        return ""
    prefix = f"\n\\bibliographystyle{{{style}}}" if style else ""
    return "\n\\clearpage\n" + prefix + "\n\\bibliography{references}\n"


def _disclosure(evidence: dict[str, Any], title: str, text: str) -> str:
    if evidence.get("mode") != "synthetic_preview":
        return ""
    return f"\n\\section*{{{title}}}\n{text}\n"


def _manuscript_inputs(
    paths: dict[str, Path], sections: list[tuple[str, Path]]
) -> str:
    from .paper_asset_placement import section_asset_placements, write_assembly_fragments

    placements = section_asset_placements(paths["root"], sections[1:])
    write_assembly_fragments(placements)
    inputs = []
    for name, _path in sections[1:]:
        inputs.append(f"\\input{{sections/{name}}}")
        for item in placements:
            if item.stage == name.split("_", 1)[-1]:
                relative = item.path.relative_to(paths["paper"]).with_suffix("").as_posix()
                inputs.append(f"\\input{{{relative}}}")
    return "\n".join(inputs)


def _render_main(
    title: str, inputs: str, bibliography: str, disclosure: str,
    unicode_package: str, template: dict[str, Any], markers: tuple[str, ...],
    error_factory: Callable[[str, list[str]], Exception],
) -> str:
    title_tex = latex_text(title)
    abstract = "\\begin{abstract}\n\\input{sections/00_abstract}\n\\end{abstract}\n\n"
    custom = str(template["custom_text"])
    if custom:
        return _render_custom(
            custom, title_tex, abstract, inputs, disclosure, bibliography,
            unicode_package, str(template["documentclass"]), markers, error_factory,
        )
    front, post_abstract = _front_matter(
        title_tex, abstract, str(template["title_mode"]),
        bool(template["abstract_before_title"]),
    )
    preamble = _common_preamble(
        str(template["geometry"]), bool(template["hyperref"])
    )
    return (
        str(template["documentclass"]) + "\n" + str(template["venue_preamble"]) + "\n"
        + unicode_package + preamble + front + post_abstract + inputs
        + disclosure + bibliography + "\\end{document}\n"
    )


def _common_preamble(geometry: str, hyperref: bool) -> str:
    return (
        geometry + "\\usepackage{amsmath,amssymb,amsfonts}\n"
        "\\usepackage{graphicx}\n\\usepackage{booktabs}\n"
        "\\usepackage{tabularx}\n\\usepackage{multirow}\n"
        "\\usepackage{microtype}\n"
        + ("\\usepackage[hidelinks]{hyperref}\n" if hyperref else "")
        + "\\graphicspath{{../figures/plots/}{../figures/diagrams/}{../figures/assets/}}\n"
    )


def _front_matter(
    title: str, abstract: str, mode: str, abstract_before_title: bool
) -> tuple[str, str]:
    if mode == "icml":
        return (
            f"\\icmltitlerunning{{{title}}}\n\\begin{{document}}\n\\twocolumn[\n"
            f"  \\icmltitle{{{title}}}\n  \\begin{{icmlauthorlist}}\n"
            "    \\icmlauthor{Anonymous Authors}{anon}\n  \\end{icmlauthorlist}\n"
            "  \\icmlaffiliation{anon}{Anonymous Institution}\n  \\vskip 0.3in\n]\n"
            "\\printAffiliationsAndNotice{}\n\n",
            abstract,
        )
    if abstract_before_title:
        return (
            f"\\title{{{title}}}\n\\author{{Anonymous Authors}}\n\\date{{}}\n\n"
            "\\begin{document}\n" + abstract + "\\maketitle\n\n",
            "",
        )
    return (
        f"\\title{{{title}}}\n\\author{{Anonymous Authors}}\n\\date{{}}\n\n"
        "\\begin{document}\n\\maketitle\n\n",
        abstract,
    )


def _render_custom(
    existing: str, title: str, abstract: str, inputs: str, disclosure: str,
    bibliography: str, unicode_package: str, documentclass: str,
    markers: tuple[str, ...], error_factory: Callable[[str, list[str]], Exception],
) -> str:
    additions = _custom_preamble_additions(existing, unicode_package)
    body = (
        f"\\title{{{title}}}\n\\author{{Anonymous Authors}}\n\\date{{}}\n"
        "\\maketitle\n\n" + abstract + inputs + disclosure
    )
    marker = next(
        (value for value in markers if value in existing
         and existing.find(value) > existing.find("\\begin{document}")), ""
    )
    outside = existing.replace(marker, "", 1) if marker else existing
    custom_bibliography = bool(re.search(r"\\bibliography\{[^}]+\}", outside))
    if not custom_bibliography:
        body += bibliography
    main = _inject_custom_content(
        existing, marker, additions, body, documentclass, error_factory
    )
    if custom_bibliography:
        main = re.sub(r"\\bibliography\{[^}]+\}", r"\\clearpage\n\\bibliography{references}", main)
    return main


def _custom_preamble_additions(existing: str, unicode_package: str) -> str:
    loaded = {
        package.strip()
        for match in re.finditer(r"\\usepackage(?:\[[^\]]*\])?\{([^}]+)\}", existing)
        for package in match.group(1).split(",")
    }
    additions = []
    if unicode_package and "ctex" not in loaded:
        additions.append(unicode_package.rstrip())
    for package in ("amsmath", "amssymb", "amsfonts", "graphicx", "booktabs",
                    "tabularx", "multirow", "microtype"):
        if package not in loaded:
            additions.append(f"\\usepackage{{{package}}}")
    if "\\graphicspath" not in existing:
        additions.append("\\graphicspath{{../figures/plots/}{../figures/diagrams/}{../figures/assets/}}")
    return "\n".join(additions) + "\n"


def _inject_custom_content(
    existing: str, marker: str, additions: str, body: str,
    documentclass: str, error_factory: Callable[[str, list[str]], Exception],
) -> str:
    if marker:
        main = existing.replace(marker, body, 1)
        begin = main.find("\\begin{document}")
        return main[:begin] + additions + main[begin:] if begin >= 0 else main
    begin = re.search(r"\\begin\{document\}", existing)
    if begin:
        preamble = existing[:begin.start()].rstrip()
    elif documentclass:
        preamble = documentclass
    else:
        raise error_factory("assembly", ["custom template is missing \\begin{document}"])
    return preamble + "\n" + additions + "\\begin{document}\n" + body + "\\end{document}\n"


def _persist_template_resolution(
    paths: dict[str, Path], state: dict[str, Any], style: dict[str, Any],
    metadata: dict[str, Any],
) -> None:
    state["venue_template"] = metadata
    state["updated_at"] = time.time()
    write_json(paths["state"], state)
    style["resolved_template"] = metadata
    write_json(paths["style"], style)
