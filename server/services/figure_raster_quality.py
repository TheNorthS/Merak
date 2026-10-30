"""Raster and rich-SVG quality gates for figure artifacts."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from PIL import Image, ImageChops, ImageStat

from .figure_artifact_support import _longest_false_run


class FigureRasterQualityMixin:
    @staticmethod
    def raster_layout_issues(path: str | Path) -> list[str]:
        """Detect blank/cropped renderer output that dimensions alone cannot catch."""
        output = Path(path).expanduser().resolve()
        try:
            with Image.open(output) as opened:
                original_bands = opened.getbands()
                image = opened.convert("RGBA")
        except OSError:
            return ["raster output cannot be decoded"]

        image.thumbnail((360, 360), Image.Resampling.LANCZOS)
        width, height = image.size
        total = max(1, width * height)
        alpha = image.getchannel("A")
        alpha_values = list(alpha.getdata())
        opaque_ratio = sum(value > 16 for value in alpha_values) / total
        if "A" in original_bands and opaque_ratio < 0.65:
            return [f"raster canvas is mostly transparent ({opaque_ratio:.0%} opaque)"]

        row_occupied = [
            any(alpha.getpixel((x, y)) > 16 for x in range(width))
            for y in range(height)
        ]
        transparent_gap = _longest_false_run(row_occupied) / max(1, height)
        if "A" in original_bands and transparent_gap > 0.30:
            return [
                f"raster contains a large transparent horizontal gap ({transparent_gap:.0%} of height)"
            ]

        composite = Image.new("RGB", image.size, "#ffffff")
        composite.paste(image, mask=alpha)
        corners = [
            composite.getpixel((0, 0)),
            composite.getpixel((max(0, width - 1), 0)),
            composite.getpixel((0, max(0, height - 1))),
            composite.getpixel((max(0, width - 1), max(0, height - 1))),
        ]
        background = max(set(corners), key=corners.count)
        difference = ImageChops.difference(
            composite,
            Image.new("RGB", composite.size, background),
        ).convert("L")
        mask = difference.point(lambda value: 255 if value > 18 else 0)
        bbox = mask.getbbox()
        if not bbox:
            return ["raster contains no visible diagram content"]
        width_coverage = (bbox[2] - bbox[0]) / max(1, width)
        height_coverage = (bbox[3] - bbox[1]) / max(1, height)
        edge_margins = {
            "left": bbox[0] / max(1, width),
            "right": (width - bbox[2]) / max(1, width),
            "top": bbox[1] / max(1, height),
            "bottom": (height - bbox[3]) / max(1, height),
        }
        issues = []
        if width_coverage < 0.40:
            issues.append(
                f"diagram occupies only {width_coverage:.0%} of raster width"
            )
        if height_coverage < 0.38:
            issues.append(
                f"diagram occupies only {height_coverage:.0%} of raster height"
            )
        # Matplotlib's tight bounding box routinely leaves only 1--2 pixels
        # between an axis spine/marker and the raster boundary.  Treating that
        # normal anti-aliased inset as a crop produced false blockers for every
        # generated preview.  Reserve the blocker for content that is truly
        # flush with the canvas (roughly <=0.5% at the review thumbnail size).
        cramped_edges = [
            name for name, margin in edge_margins.items() if margin < 0.005
        ]
        if cramped_edges:
            issues.append(
                "diagram content touches or is likely cropped at the "
                + ", ".join(cramped_edges)
                + " canvas edge"
            )
        return issues

    @classmethod
    def raster_visual_quality_issues(cls, path: str | Path) -> list[str]:
        """Bind visual review to a decodable, legible, non-degenerate render."""

        issues = list(cls.raster_layout_issues(path))
        output = Path(path).expanduser().resolve()
        try:
            with Image.open(output) as opened:
                image = opened.convert("RGB")
        except OSError:
            return list(dict.fromkeys([*issues, "raster output cannot be decoded"]))
        width, height = image.size
        if width < 1000 or height < 450:
            issues.append(f"raster preview is too small ({width}x{height})")
        sample = image.copy()
        sample.thumbnail((420, 420), Image.Resampling.LANCZOS)
        grayscale = sample.convert("L")
        contrast = float(ImageStat.Stat(grayscale).stddev[0])
        if contrast < 8.0:
            issues.append(f"raster has insufficient visual contrast ({contrast:.1f})")
        quantized = sample.quantize(colors=16, method=Image.Quantize.MEDIANCUT)
        used_colors = len(quantized.getcolors(maxcolors=16) or [])
        if used_colors < 3:
            issues.append(
                f"raster has insufficient visual differentiation ({used_colors} colors)"
            )
        return list(dict.fromkeys(issues))

    @staticmethod
    def rich_svg_source_issues(path: str | Path) -> list[str]:
        """Reject SVG marker definitions known to render inconsistently."""

        source = Path(path).expanduser().resolve()
        try:
            root = ET.fromstring(source.read_bytes())
        except (OSError, ET.ParseError):
            return ["rich SVG source is malformed"]
        issues: list[str] = []
        no_fill_classes: set[str] = set()
        for element in root.iter():
            if element.tag.rsplit("}", 1)[-1].casefold() != "style":
                continue
            no_fill_classes.update(
                match.group(1)
                for match in re.finditer(
                    r"\.([A-Za-z_][\w-]*)\s*\{[^}]*\bfill\s*:\s*none\b[^}]*\}",
                    element.text or "",
                    flags=re.IGNORECASE,
                )
            )
        for marker in (
            element
            for element in root.iter()
            if element.tag.rsplit("}", 1)[-1].casefold() == "marker"
        ):
            marker_id = str(marker.attrib.get("id") or "unnamed")
            view_box = str(marker.attrib.get("viewBox") or "").split()
            if len(view_box) != 4:
                issues.append(
                    f"rich SVG marker {marker_id} has no deterministic four-number viewBox"
                )
            if str(marker.attrib.get("markerUnits") or "") != "userSpaceOnUse":
                issues.append(
                    f"rich SVG marker {marker_id} must use markerUnits=userSpaceOnUse"
                )
        for path_element in (
            element
            for element in root.iter()
            if element.tag.rsplit("}", 1)[-1].casefold() == "path"
        ):
            classes = set(str(path_element.attrib.get("class") or "").split())
            if (
                classes.intersection(no_fill_classes)
                and str(path_element.attrib.get("fill") or "").casefold() != "none"
            ):
                issues.append(
                    "rich SVG open paths using a CSS fill:none class must also "
                    "inline fill=none for faithful PDF/PNG rendering"
                )
                break
        return issues

    @staticmethod
    def predictive_architecture_semantic_issues(
        metadata: dict[str, Any],
        visible_text: str,
    ) -> list[str]:
        """Reject protocol storyboards mislabeled as predictive architectures."""
        contribution = (metadata.get('scene_contract') or {}).get('contribution_type')
        if contribution and contribution != 'model_architecture':
            return []
        blueprint = (
            metadata.get("architecture_blueprint")
            if isinstance(metadata.get("architecture_blueprint"), dict)
            else {}
        )
        components = [
            item for item in blueprint.get("components") or []
            if isinstance(item, dict)
        ]
        source_text = " ".join(
            " ".join((
                str(item.get("display_name") or ""),
                str(item.get("label") or ""),
                str(item.get("source_symbol") or ""),
                str(item.get("operation") or ""),
            ))
            for item in components
        ).casefold()
        predictive_source = bool(re.search(
            r"\b(?:classifier|task[_ ]?head|logits?|residual|encoder|"
            r"transformer|attention|conv\d*d?|softmax|layernorm)\b",
            source_text,
        ))
        if not predictive_source:
            return []
        rendered = " ".join(str(visible_text or "").split()).casefold()
        has_internal_path = bool(re.search(
            r"\b(?:residual|skip connection|layer ?norm|encoder|backbone|"
            r"projection|embedding|transformer|attention|convolution|conv\d*d?|"
            r"dense layer|block stack)\b",
            rendered,
        ))
        has_prediction_path = bool(re.search(
            r"\b(?:task head|classification head|prediction head|logits?|"
            r"probabilit(?:y|ies)|softmax)\b",
            rendered,
        ))
        issues: list[str] = []
        if not has_internal_path:
            issues.append(
                "predictive method figure omits source-defined model internals; "
                "a protocol or audit storyboard is not a model architecture"
            )
        if not has_prediction_path:
            issues.append(
                "predictive method figure omits the implemented prediction/head path"
            )
        return issues

    @staticmethod
    def rich_svg_render_issues(path: str | Path) -> list[str]:
        """Detect giant solid arrowheads or other renderer-created ink blobs."""

        output = Path(path).expanduser().resolve()
        try:
            with Image.open(output) as opened:
                sample = opened.convert("RGB")
        except OSError:
            return ["rich SVG raster output cannot be decoded"]
        sample.thumbnail((420, 420), Image.Resampling.LANCZOS)
        width, height = sample.size
        pixels = list(sample.getdata())
        dark = [max(pixel) <= 45 for pixel in pixels]
        visited = bytearray(len(dark))
        largest = 0
        largest_bounds = (0, 0, 0, 0)
        for start, occupied in enumerate(dark):
            if not occupied or visited[start]:
                continue
            stack = [start]
            visited[start] = 1
            size = 0
            min_x = max_x = start % width
            min_y = max_y = start // width
            while stack:
                index = stack.pop()
                size += 1
                x = index % width
                y = index // width
                min_x = min(min_x, x)
                max_x = max(max_x, x)
                min_y = min(min_y, y)
                max_y = max(max_y, y)
                for neighbor in (
                    index - 1 if x > 0 else -1,
                    index + 1 if x + 1 < width else -1,
                    index - width if y > 0 else -1,
                    index + width if y + 1 < height else -1,
                ):
                    if neighbor >= 0 and dark[neighbor] and not visited[neighbor]:
                        visited[neighbor] = 1
                        stack.append(neighbor)
            if size > largest:
                largest = size
                largest_bounds = (min_x, min_y, max_x, max_y)
        total = max(1, width * height)
        component_ratio = largest / total
        component_width = (largest_bounds[2] - largest_bounds[0] + 1) / max(1, width)
        component_height = (largest_bounds[3] - largest_bounds[1] + 1) / max(1, height)
        if (
            component_ratio > 0.0025
            and component_width > 0.12
            and component_height > 0.025
        ):
            return [
                "rich SVG render contains an implausibly large near-black solid "
                f"component ({component_ratio:.1%} of preview); check arrow markers"
            ]
        return []


