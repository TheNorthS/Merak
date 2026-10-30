"""Draw.io and Mermaid publication-text and layout policies."""

from __future__ import annotations

import html
import json
import math
import re
import textwrap
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from .figure_artifact_support import _semantic_tokens, _sha256


def _prompt_publication_text(source: Path, project_root: Path) -> str:
    """Project authored image requests, never runtime protocol/audit field names.

This is semantic-source inspection, not image acceptance. Native image review
and the generator's independent hash/provenance gate remain mandatory.
"""
    try:
        payload = json.loads(source.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("Image publication prompt source is unreadable") from error
    if not isinstance(payload, dict):
        raise ValueError("Image publication prompt source must be an object")
    if payload.get("protocol") != "merak-paperbanana-v1":
        prompt = payload.get("prompt")
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError("Image publication prompt source has no authored scientific request")
        revised = payload.get("revised_prompt")
        return "\n".join(value.strip() for value in (prompt, revised) if isinstance(value, str) and value.strip())
    initial = payload.get("initial_prompt")
    description = payload.get("description")
    if payload.get("schema") != 1 or not isinstance(initial, str) or not isinstance(description, str) or not description.strip():
        raise ValueError("Paperbanana publication source lacks its authored scientific request")
    scientific = re.search(r"SCIENTIFIC REQUEST\s*\n(.*?)\nCONTENT INTEGRITY", initial, re.DOTALL)
    if scientific is None or not scientific.group(1).strip():
        raise ValueError("Paperbanana publication source lacks scientific request and public-label sections")
    accepted = payload.get("accepted_round")
    if not isinstance(accepted, int) or isinstance(accepted, bool) or accepted < 1:
        raise ValueError("Paperbanana publication source lacks a valid accepted rendering round")
    paths, hashes = payload.get("artifacts"), payload.get("artifact_sha256")
    if not isinstance(paths, dict) or not isinstance(hashes, dict):
        raise ValueError("Paperbanana publication source lacks bound rendering-specification artifacts")
    key = f"round_{accepted:02d}/style_spec.txt"
    relative, expected = paths.get(key), hashes.get(key)
    if not isinstance(relative, str) or not isinstance(expected, str) or not expected:
        raise ValueError("Paperbanana accepted rendering specification is not hash-bound")
    path = (project_root / relative).resolve()
    if not path.is_relative_to(project_root.resolve()) or not path.is_file() or _sha256(path) != expected:
        raise ValueError("Paperbanana accepted rendering specification is missing, outside the project, or stale")
    style = path.read_text(encoding="utf-8-sig")
    if not style.strip():
        raise ValueError("Paperbanana accepted rendering specification is empty")
    return "\n".join((description.strip(), scientific.group(1).strip(), style.strip()))


class FigureDiagramTextMixin:
    @staticmethod
    def _source_semantic_text(source: Path) -> str:
        raw = source.read_text(encoding="utf-8-sig", errors="replace")
        if source.suffix.casefold() == ".excalidraw":
            try:
                scene = json.loads(raw)
            except json.JSONDecodeError:
                return raw
            return "\n".join(
                str(element.get("text") or "").strip()
                for element in scene.get("elements", [])
                if isinstance(element, dict)
                and element.get("type") == "text"
                and str(element.get("text") or "").strip()
            )
        if source.suffix.casefold() == ".json":
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                return raw
            if isinstance(payload, dict) and isinstance(payload.get("nodes"), list):
                visible = [
                    str(value).strip()
                    for collection, fields in (
                        (payload.get("nodes") or [], ("label", "sublabel")),
                        (payload.get("edges") or [], ("label",)),
                        (payload.get("groups") or [], ("label",)),
                        (payload.get("labels") or [], ("text",)),
                    )
                    for item in collection
                    if isinstance(item, dict)
                    for field in fields
                    for value in (item.get(field),)
                    if str(value or "").strip()
                ]
                return "\n".join(visible)
        if source.suffix.casefold() == ".svg":
            try:
                svg_root = ET.fromstring(raw)
            except ET.ParseError:
                return raw
            return "\n".join(
                " ".join("".join(element.itertext()).split())
                for element in svg_root.iter()
                if element.tag.rsplit("}", 1)[-1].casefold() == "text"
                and "".join(element.itertext()).strip()
            )
        if source.suffix.casefold() not in {".drawio", ".dio"}:
            return raw
        try:
            root = ET.fromstring(raw)
        except ET.ParseError:
            return raw
        labels = []
        for cell in root.iter("mxCell"):
            value = html.unescape(str(cell.attrib.get("value") or ""))
            value = " ".join(re.sub(r"<[^>]+>", " ", value).split())
            if value:
                labels.append(value)
        return "\n".join(labels)

    @classmethod
    def _publication_semantic_text(
        cls,
        item: dict[str, Any],
        project_root: Path,
        source: Path,
    ) -> str:
        """Return text that can actually appear in the manuscript figure.

        Diagram sources are themselves visual scene descriptions, but a Python
        plotting script is implementation provenance rather than publication
        content.  For code-backed figures, inspect the hash-bound SVG variant
        instead of treating variable names, data paths, and renderer arguments
        as visible labels.
        """
        if source.name.casefold().endswith(".prompt.json"):
            return _prompt_publication_text(source, project_root)
        if source.suffix.casefold() != ".py":
            return cls._source_semantic_text(source)

        metadata = dict(item.get("metadata") or {})
        variants = dict(metadata.get("rendered_variants") or {})
        variant_hashes = dict(metadata.get("rendered_variant_sha256") or {})
        candidates: list[tuple[str, str]] = []
        svg_variant = str(variants.get("svg") or "").strip()
        if svg_variant:
            candidates.append((svg_variant, str(variant_hashes.get("svg") or "")))
        output_value = str(item.get("output_path") or "").strip()
        if output_value and Path(output_value).suffix.casefold() == ".svg":
            candidates.append((output_value, str(item.get("output_sha256") or "")))

        seen: set[str] = set()
        for raw_path, expected_hash in candidates:
            candidate = Path(raw_path).expanduser()
            candidate = (
                candidate if candidate.is_absolute() else project_root / candidate
            ).resolve()
            marker = str(candidate).casefold()
            if marker in seen:
                continue
            seen.add(marker)
            try:
                candidate.relative_to(project_root)
            except ValueError:
                continue
            if not candidate.is_file() or candidate.suffix.casefold() != ".svg":
                continue
            if expected_hash and _sha256(candidate) != expected_hash:
                continue
            return cls._source_semantic_text(candidate)
        return ""

    @staticmethod
    def _drawio_style_number(style: str, key: str, default: float) -> float:
        match = re.search(rf"(?:^|;){re.escape(key)}=([0-9.]+)", style)
        if not match:
            return default
        try:
            return float(match.group(1))
        except (TypeError, ValueError):
            return default

    @classmethod
    def _drawio_text_budget(
        cls,
        value: str,
        style: str,
        width: float,
        height: float,
    ) -> tuple[int, int, float]:
        """Return required lines, available lines, and the required box height.

        Draw.io stores authored line breaks both as XML newlines (``&#xa;``)
        and HTML ``<br>`` tags.  Preserve those breaks before estimating any
        additional wrapping.  The previous implementation collapsed them to
        spaces, which made a visibly correct three-line label fail as four
        estimated lines after rendering.
        """
        raw = html.unescape(str(value or ""))
        raw = re.sub(r"(?i)<br\s*/?>", "\n", raw)
        raw = re.sub(r"(?i)</(?:div|p|li|tr|h[1-6])\s*>", "\n", raw)
        raw = re.sub(r"<[^>]+>", "", raw)
        authored_lines = raw.splitlines() or [raw]
        font_size = cls._drawio_style_number(style, "fontSize", 16.0)
        spacing_top = cls._drawio_style_number(style, "spacingTop", 0.0)
        spacing_bottom = cls._drawio_style_number(style, "spacingBottom", 0.0)
        chars_per_line = max(
            8,
            int(max(20.0, width - 18) / max(4.5, font_size * 0.53)),
        )
        required_lines = 0
        for authored in authored_lines:
            normalized = " ".join(authored.split())
            if not normalized:
                required_lines += 1
                continue
            required_lines += max(
                1,
                len(textwrap.wrap(
                    normalized,
                    width=chars_per_line,
                    break_long_words=False,
                    break_on_hyphens=False,
                )),
            )
        line_height = max(12.0, font_size * 1.35)
        usable_height = max(20.0, height - spacing_top - spacing_bottom - 4.0)
        allowed_lines = max(1, int(usable_height / line_height))
        required_height = (
            required_lines * line_height + spacing_top + spacing_bottom + 6.0
        )
        return required_lines, allowed_lines, required_height

    @classmethod
    def autofit_drawio_text(cls, xml: str) -> tuple[str, list[str]]:
        """Increase undersized Draw.io text cells before the first render.

        This is a deterministic geometry repair, not a scientific revision.
        It prevents a sequence of model calls that differ only by a few pixels
        of box height.  Downstream overlap and canvas checks still reject a
        scene when the expanded geometry conflicts with other content.
        """
        try:
            root = ET.fromstring(xml)
        except ET.ParseError:
            return xml, []
        adjustments: list[str] = []
        for cell in root.iter("mxCell"):
            if cell.attrib.get("vertex") != "1":
                continue
            geometry = next(
                (child for child in cell if child.tag.rsplit("}", 1)[-1] == "mxGeometry"),
                None,
            )
            if geometry is None:
                continue
            value = str(cell.attrib.get("value") or "")
            if not value.strip():
                continue
            style = str(cell.attrib.get("style") or "")
            try:
                width = float(geometry.attrib.get("width") or 180)
                height = float(geometry.attrib.get("height") or 70)
            except (TypeError, ValueError):
                continue
            required, allowed, required_height = cls._drawio_text_budget(
                value,
                style,
                width,
                height,
            )
            if required <= allowed:
                continue
            new_height = max(height, math.ceil(required_height))
            geometry.set("height", str(int(new_height)))
            adjustments.append(
                f"{cell.attrib.get('id') or 'unnamed'}:{height:g}->{new_height:g}"
            )
        if not adjustments:
            return xml, []
        return ET.tostring(root, encoding="unicode"), adjustments

    @classmethod
    def drawio_text_layout_issues(cls, source: Path) -> list[str]:
        """Detect labels that cannot fit their declared Draw.io geometry."""
        try:
            root = ET.fromstring(source.read_text(encoding="utf-8-sig", errors="replace"))
        except (OSError, ET.ParseError):
            return ["drawio source cannot be parsed for text layout"]
        issues: list[str] = []
        for cell in root.iter("mxCell"):
            if cell.attrib.get("vertex") != "1":
                continue
            geometry = next(
                (child for child in cell if child.tag.rsplit("}", 1)[-1] == "mxGeometry"),
                None,
            )
            if geometry is None:
                continue
            raw_value = str(cell.attrib.get("value") or "")
            label = " ".join(
                re.sub(r"<[^>]+>", " ", html.unescape(raw_value)).split()
            )
            if not label:
                continue
            style = str(cell.attrib.get("style") or "")
            if "text;" not in style and re.search(r"(?:\.\.\.|…)", label):
                cell_id = str(cell.attrib.get("id") or "unnamed")
                issues.append(
                    f"drawio cell {cell_id} contains a truncated label"
                )
            try:
                width = float(geometry.attrib.get("width") or 180)
                height = float(geometry.attrib.get("height") or 70)
            except (TypeError, ValueError):
                continue
            required_lines, allowed_lines, _ = cls._drawio_text_budget(
                raw_value,
                style,
                width,
                height,
            )
            if required_lines > allowed_lines:
                cell_id = str(cell.attrib.get("id") or "unnamed")
                issues.append(
                    f"drawio cell {cell_id} needs {required_lines} text lines "
                    f"but its box allows {allowed_lines}"
                )
        return issues

    @staticmethod
    def drawio_render_text_issues(source: Path, pdf_path: Path) -> list[str]:
        """Verify that Draw.io labels survived the SVG-to-PDF renderer boundary.

        Draw.io SVG uses XHTML ``foreignObject`` labels with SVG ``text``
        fallbacks.  Some converters silently render the boxes and arrows while
        dropping every label, which geometric raster checks cannot detect.
        """
        try:
            root = ET.fromstring(
                source.read_text(encoding="utf-8-sig", errors="replace")
            )
        except (OSError, ET.ParseError):
            return ["drawio source cannot be parsed for render-text verification"]
        labels: list[str] = []
        for cell in root.iter("mxCell"):
            value = html.unescape(str(cell.attrib.get("value") or ""))
            value = " ".join(re.sub(r"<[^>]+>", " ", value).split())
            if len(value) >= 2:
                labels.append(value)
        labels = list(dict.fromkeys(labels))
        if not labels:
            return []
        if not pdf_path.is_file() or pdf_path.stat().st_size == 0:
            return ["drawio paper PDF is missing for render-text verification"]
        try:
            import fitz

            document = fitz.open(pdf_path)
            rendered = " ".join(page.get_text("text") for page in document)
            document.close()
        except Exception as exc:
            return [f"drawio paper PDF text cannot be inspected: {exc}"]

        def normalized(value: str) -> str:
            return re.sub(r"[^0-9a-z]+", "", value.casefold())

        rendered_normalized = normalized(rendered)
        if not rendered_normalized:
            return ["drawio paper PDF contains no extractable labels"]
        matched = sum(
            1
            for label in labels
            if normalized(label) and normalized(label) in rendered_normalized
        )
        required = min(len(labels), max(2, math.ceil(len(labels) * 0.6)))
        if matched < required:
            return [
                "drawio paper PDF retained only "
                f"{matched}/{len(labels)} source labels; at least {required} are required"
            ]
        return []

    @staticmethod
    def mermaid_layout_issues(source: Path) -> list[str]:
        """Reject paper diagrams that become unreadable after column-width scaling."""
        try:
            code = source.read_text(encoding="utf-8-sig", errors="replace")
        except OSError:
            return ["mermaid source cannot be read for layout checks"]
        raw_labels = {
            node_id: raw_label.strip().strip(chr(34) + chr(39))
            for node_id, raw_label in re.findall(
                r"([A-Za-z0-9_]+)\s*[\[\(\{]+([^\]\)\}]+)",
                code,
            )
        }
        labels = {
            node_id: " ".join(
                re.sub(r"<[^>]+>", " ", html.unescape(raw_label)).split()
            )
            for node_id, raw_label in raw_labels.items()
        }
        edge_count = sum(
            1
            for line in code.splitlines()
            if re.search(r"(?:-->|==>|-\.[^>]*->)", line)
        )
        issues: list[str] = []
        if len(labels) > 24:
            issues.append(
                f"mermaid diagram has {len(labels)} nodes; paper limit is 24"
            )
        if edge_count > 30:
            issues.append(
                f"mermaid diagram has {edge_count} edges; paper limit is 30"
            )
        for node_id, label in labels.items():
            # Mermaid honors explicit HTML line breaks.  Keep those boundaries
            # when estimating the rendered height; flattening them made the
            # gate and the repair agent disagree about what "four lines"
            # meant.  Long explicit lines still count as multiple paper-width
            # lines, so a four-row label cannot hide an unreadably wide row.
            raw_label = raw_labels.get(node_id, "")
            explicit_rows = re.split(r"<br\s*/?>", raw_label, flags=re.IGNORECASE)
            cleaned_rows = [
                " ".join(
                    re.sub(r"<[^>]+>", " ", html.unescape(row)).split()
                )
                for row in explicit_rows
            ]
            required_lines = sum(
                max(
                    1,
                    len(
                        textwrap.wrap(
                            row,
                            width=32,
                            break_long_words=True,
                            break_on_hyphens=False,
                        )
                    ),
                )
                for row in cleaned_rows
            ) if cleaned_rows else len(
                textwrap.wrap(
                    label,
                    width=32,
                    break_long_words=True,
                    break_on_hyphens=False,
                )
            )
            if required_lines > 4:
                longest_row = max((len(row) for row in cleaned_rows), default=0)
                issues.append(
                    f"mermaid node {node_id} needs {required_lines} text lines; "
                    "paper limit is 4 after honoring explicit <br/> breaks "
                    f"and wrapping each row at 32 characters (longest row: {longest_row})"
                )
        return issues

    @staticmethod
    def mermaid_concept_present(term: str, source_text: str) -> bool:
        """Match required scientific concepts without demanding one phrase."""
        required = " ".join(re.sub(
            r"[^0-9A-Za-z]+", " ", str(term or "")
        ).split()).casefold()
        source = " ".join(re.sub(
            r"[^0-9A-Za-z]+", " ", str(source_text or "")
        ).split()).casefold()
        concept_aliases = {
            "leakage safe split": (
                "leakage safe split", "group disjoint", "record disjoint",
                "subject disjoint", "source disjoint", "identity isolated",
                "protected partition",
            ),
            "held out evaluation": (
                "held out evaluation", "held out condition", "locked test",
                "final evaluation", "no further selection",
            ),
            "study data": (
                "study data", "versioned data", "versioned input",
                "records labels metadata", "analysis units",
            ),
        }
        aliases = concept_aliases.get(required)
        if aliases and any(alias in source for alias in aliases):
            return True
        term_tokens = _semantic_tokens(required)
        source_tokens = _semantic_tokens(source)
        required_overlap = min(2, len(term_tokens))
        return bool(required_overlap and len(term_tokens & source_tokens) >= required_overlap)


