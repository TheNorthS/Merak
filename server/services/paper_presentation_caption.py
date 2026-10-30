"""Project risk captions from exact bound source populations, never raw metadata.

Only a verified trusted risk plot's public figure float receives a paper-side
caption. Frozen science, original captions and authored prose stay unchanged;
the PRINT owner recomputes this same transform when validating derived sources.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Callable

from .paper_derived_figure_binding import bound_original_inputs, local_path, stable_json_sha256
from .paper_evidence import _latex
from .paper_plot_semantics_projection import _metric, _rows, synthetic_source
from .paper_trusted_plot_source import match_trusted_plot


_FIGURE = re.compile(r"\\begin\{(?P<kind>figure\*?)\}(?P<body>.*?)\\end\{(?P=kind)\}", re.DOTALL)
_GRAPHIC = re.compile(r"\\includegraphics\*?(?:\s*\[[^]]*\])?\s*\{([^{}]+)\}")
_LABEL = re.compile(r"\\label\s*\{([^{}]+)\}")
_CAPTION = re.compile(r"\\caption\b(\*?)(?:\s*\[([^]]*)\])?\s*\{")


def caption_contracts(root: Path, packets: list[dict[str, Any]]) -> dict[Path, dict[str, Any]]:
    """Only exact current risk sources can declare an independent presentation caption."""
    from .paper_derived_figure_rendering import _current_entry

    contracts = {}
    for packet in packets:
        relative = str(packet.get("source") or "")
        if not relative or Path(relative).suffix.casefold() != ".py":
            continue
        source = local_path(root, relative)
        name, parameters, _template = match_trusted_plot(source.read_text(encoding="utf-8-sig"))
        if name != "risk_coverage":
            continue
        entry = _current_entry(root, str(packet.get("asset_id") or ""))
        bound, inventory = bound_original_inputs(root, entry)
        if (packet.get("original_entry_sha256") != stable_json_sha256(entry)
                or packet.get("original_inputs_sha256") != bound or packet.get("csv_inventory") != inventory
                or packet.get("source") != entry.get("source_path")
                or packet.get("original_path") != entry.get("output_path")
                or parameters["data_path"] not in {item["path"] for item in inventory}):
            raise ValueError("Risk caption lacks its exact original scientific source binding")
        label = packet.get("label")
        if (not isinstance(label, str) or not re.fullmatch(r"fig:[A-Za-z0-9][A-Za-z0-9:_.-]*", label)
                or label != (entry.get("metadata") or {}).get("label")):
            raise ValueError("Risk caption requires one explicit canonical public figure label")
        original, derived = local_path(root, packet["original_path"]), local_path(root, packet["output_path"])
        if original in contracts:
            raise ValueError("Duplicate risk caption presentation identity")
        contracts[original] = {"label": label, "derived": derived,
                               "caption": _latex(_risk_caption(root, parameters))}
    return contracts


def _risk_caption(root: Path, parameters: dict[str, Any]) -> str:
    rows = _rows(root, parameters)
    metric = _metric(rows, parameters, "risk_coverage")
    populations = {str(row.get("dataset") or "") for row in rows}
    groups: dict[tuple[str, str], list[dict]] = {}
    for row in rows:
        key = str(row["method"]), str(row.get("dataset") or "")
        groups.setdefault(key, []).append(row)
    named = bool(populations - {""})
    synthetic = synthetic_source(root, parameters, rows)
    quantity = (f"Recorded {metric} values and retained-risk records"
                if all(str(row.get("risk") or "").strip() for row in rows) else f"{metric} records")
    caption = quantity + " at the declared retained coverages, shown separately by "
    caption += "dataset and method. " if named else "method. "
    if synthetic:
        caption += ("Dataset names identify generated scenario labels, not measurements from those datasets. "
                    "Vertical intervals show assigned scenario bounds, not population confidence intervals.")
    else:
        caption += "Vertical intervals show the supplied bounds."
    connected = any(len(group) > 1 for group in groups.values())
    if connected:
        caption += (" Lines and shaded intervals connect only records from the same dataset and method."
                    if named else " Lines and shaded intervals connect only records of the same method.")
    if len(populations) > 1:
        caption += " Records from different datasets are not joined."
        if not connected:
            caption += " These distinct-dataset records do not establish a within-dataset coverage effect."
    return caption


def _comment_mask(text: str) -> str:
    """Preserve source offsets while excluding real TeX comments from command parsing."""
    lines = []
    for line in text.splitlines(keepends=True):
        match = re.search(r"(?<!\\)(?:\\\\)*%", line)
        if match is not None:
            offset = match.end() - 1
            line = line[:offset] + "".join(character if character in "\r\n" else " " for character in line[offset:])
        lines.append(line)
    return "".join(lines)


def _caption_span(block: str) -> tuple[int, int]:
    commands = list(_CAPTION.finditer(block))
    if len(commands) != 1 or commands[0].group(1) or commands[0].group(2) is not None:
        raise ValueError("Risk figure needs one supported full caption, without a short or starred caption")
    start, depth = commands[0].end(), 1
    for position in range(start, len(block)):
        backslashes = len(block[:position]) - len(block[:position].rstrip("\\"))
        if backslashes % 2:
            continue
        depth += (1 if block[position] == "{" else -1 if block[position] == "}" else 0)
        if depth == 0:
            return start, position
    raise ValueError("Risk caption has unbalanced scientific text")


def project_source_captions(text: str, contracts: dict[Path, dict],
                             graphics: dict[Path, Path], resolve_graphic: Callable[[str], Path | None],
                             used: dict[Path, int]) -> str:
    """Replace only the caption body of its unique exact label/graphic figure float."""
    replacements = []
    masked = _comment_mask(text)
    for figure in _FIGURE.finditer(masked):
        block = figure.group()
        labels, raw_graphics = _LABEL.findall(block), _GRAPHIC.findall(block)
        resolved = [resolve_graphic(raw) for raw in raw_graphics]
        candidates = [path for path, contract in contracts.items()
                      if path in resolved or contract["label"] in labels]
        if not candidates:
            continue
        if len(candidates) != 1:
            raise ValueError("One risk figure float cannot consume multiple scientific caption identities")
        original, = candidates
        contract = contracts[original]
        if labels != [contract["label"]] or resolved != [original] or graphics.get(original) != contract["derived"]:
            raise ValueError("Risk caption public label, canonical graphic and derived presentation do not match")
        start, end = _caption_span(block)
        replacements.append((figure.start() + start, figure.start() + end, contract["caption"]))
        used[original] = used.get(original, 0) + 1
    for start, end, caption in reversed(replacements):
        text = text[:start] + caption + text[end:]
    return text
