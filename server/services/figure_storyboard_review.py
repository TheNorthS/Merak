"""Render competing figure storyboards and select one through native vision."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from ..utils.atomic_write import atomic_write_json


PALETTE = (
    ("#E8F1FB", "#4E82C3"), ("#E4F5F1", "#2B9A8A"),
    ("#FFF0DF", "#E89A4A"), ("#F1ECF8", "#8B72B6"),
    ("#FBEAE8", "#D9655B"), ("#EAF5EA", "#61A66A"),
)
STORYBOARD_REVIEW_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "selected_id": {"type": "string"},
        "scores": {"type": "object"},
        "selection_reason": {"type": "string"},
        "rejected_reasons": {"type": "object"},
    },
    "required": ["selected_id", "scores", "selection_reason", "rejected_reasons"],
}


def _font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    candidates = (
        Path("C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    )
    for path in candidates:
        try:
            if path.is_file():
                return ImageFont.truetype(str(path), size)
        except OSError:
            continue
    return ImageFont.load_default()


def _positions(candidate: dict[str, Any]) -> list[tuple[int, int, int, int]]:
    regions = list(candidate["regions"])
    count = len(regions)
    topology = str(candidate["topology"])
    left, top, width, height = 90, 165, 1420, 650
    gap = 34
    if topology in {"linear", "causal", "timeline"}:
        cell = (width - gap * (count - 1)) // count
        return [(left + index * (cell + gap), top + 90, cell, height - 180) for index in range(count)]
    if topology == "parallel" and count >= 3:
        branch_count = count - 2
        branch_height = (height - gap * (branch_count - 1)) // branch_count
        return [
            (left, top + 150, 260, 350),
            *[(left + 355, top + index * (branch_height + gap), 650, branch_height) for index in range(branch_count)],
            (left + 1100, top + 150, 320, 350),
        ]
    if topology in {"hierarchical", "logical"}:
        columns = min(3, max(2, math.ceil(math.sqrt(count))))
    elif topology == "matrix":
        columns = min(4, math.ceil(math.sqrt(count)))
    elif topology == "radial":
        center = (left + width // 2, top + height // 2)
        boxes = [(center[0] - 180, center[1] - 105, 360, 210)]
        radius_x, radius_y = 520, 230
        for index in range(1, count):
            angle = 2 * math.pi * (index - 1) / max(1, count - 1)
            boxes.append((
                int(center[0] + radius_x * math.cos(angle) - 145),
                int(center[1] + radius_y * math.sin(angle) - 75), 290, 150,
            ))
        return boxes
    else:
        columns = min(3, math.ceil(math.sqrt(count)))
    rows = math.ceil(count / columns)
    cell_w = (width - gap * (columns - 1)) // columns
    cell_h = (height - gap * (rows - 1)) // rows
    return [
        (left + (index % columns) * (cell_w + gap),
         top + (index // columns) * (cell_h + gap), cell_w, cell_h)
        for index in range(count)
    ]


def _wrapped(draw: ImageDraw.ImageDraw, text: str, width: int, font: Any) -> list[str]:
    words, lines = text.split(), []
    for word in words:
        candidate = " ".join([*lines[-1:], word]) if lines else word
        if lines and draw.textlength(candidate, font=font) <= width:
            lines[-1] = candidate
        else:
            lines.append(word)
    return lines[:3]


def _connection_points(
    source: tuple[int, int, int, int], target: tuple[int, int, int, int],
) -> tuple[tuple[int, int], tuple[int, int]]:
    sx, sy, sw, sh = source
    tx, ty, tw, th = target
    dx = tx + tw / 2 - (sx + sw / 2)
    dy = ty + th / 2 - (sy + sh / 2)
    if abs(dx) >= abs(dy):
        return (
            (sx + (sw if dx >= 0 else 0), sy + sh // 2),
            (tx + (0 if dx >= 0 else tw), ty + th // 2),
        )
    return (
        (sx + sw // 2, sy + (sh if dy >= 0 else 0)),
        (tx + tw // 2, ty + (0 if dy >= 0 else th)),
    )


def _draw_connection(
    draw: ImageDraw.ImageDraw, source: tuple[int, int], target: tuple[int, int],
    kind: str,
) -> None:
    color = "#52627A" if kind == "main" else "#8B72B6"
    width = 5 if kind == "main" else 3
    draw.line((*source, *target), fill=color, width=width)
    angle = math.atan2(target[1] - source[1], target[0] - source[0])
    back = (target[0] - 17 * math.cos(angle), target[1] - 17 * math.sin(angle))
    normal = (-math.sin(angle), math.cos(angle))
    draw.polygon((target, (back[0] + 9 * normal[0], back[1] + 9 * normal[1]),
                  (back[0] - 9 * normal[0], back[1] - 9 * normal[1])), fill=color)


def render_storyboard(candidate: dict[str, Any], path: Path) -> None:
    """Render a deliberately low-fidelity but spatially faithful layout thumbnail."""
    image = Image.new("RGB", (1600, 900), "white")
    draw = ImageDraw.Draw(image)
    title_font, label_font = _font(30, True), _font(24, True)
    body_font, micro_font = _font(20), _font(17)
    draw.text((70, 45), candidate["id"].replace("_", " ").title(), fill="#17233C", font=title_font)
    draw.text((70, 92), f"Topology: {candidate['topology']}", fill="#52627A", font=body_font)
    regions = list(candidate["regions"])
    boxes = _positions(candidate)
    for index, (region, box) in enumerate(zip(regions, boxes)):
        x, y, width, height = box
        fill, stroke = PALETTE[index % len(PALETTE)]
        draw.rounded_rectangle((x, y, x + width, y + height), 18, fill=fill, outline=stroke, width=4)
        draw.text((x + 20, y + 18), region["id"].replace("_", " ").title(), fill="#17233C", font=label_font)
        cursor = y + 62
        for line in _wrapped(draw, region["purpose"], width - 40, body_font):
            draw.text((x + 20, cursor), line, fill="#17233C", font=body_font)
            cursor += 27
        cursor += 8
        for line in _wrapped(draw, region["visual_grammar"], width - 40, micro_font):
            draw.text((x + 20, cursor), line, fill="#52627A", font=micro_font)
            cursor += 23
        draw.text((x + width - 48, y + height - 38), str(region["relative_weight"]), fill=stroke, font=label_font)
    box_by_id = {region["id"]: box for region, box in zip(regions, boxes)}
    for connection in candidate["connections"]:
        start, end = _connection_points(
            box_by_id[connection["from"]], box_by_id[connection["to"]],
        )
        _draw_connection(draw, start, end, connection["kind"])
    draw.text((70, 850), candidate["focal_message"], fill="#17233C", font=micro_font)
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)


async def visually_select_storyboard(
    project_path: str | Path, artifact_name: str, storyboard: dict[str, Any],
) -> dict[str, Any]:
    """Let the isolated visual reviewer select among three rendered layouts."""
    root = Path(project_path).expanduser().resolve()
    output = root / ".merak" / "figure-storyboards" / artifact_name
    paths = []
    for candidate in storyboard["candidates"]:
        path = output / f"{candidate['id']}.png"
        render_storyboard(candidate, path)
        paths.append(path)
    from .api_visual_reviewer import api_visual_reviewer

    prompt = f"""Select the strongest layout thumbnail for `{artifact_name}`.
The three attached images correspond in order to: {', '.join(item['id'] for item in storyboard['candidates'])}.
Judge only global scientific hierarchy, five-second focal message, reading path,
connector burden, whitespace balance, and suitability for domain-specific glyphs.
These are low-fidelity storyboards, so do not judge color polish or final icons.
Return one selected_id, a 0–10 score per candidate, a concise selection reason,
and a concise rejected reason for each unselected candidate."""
    response = await api_visual_reviewer.invoke(
        project_path=root, prompt=prompt,
        purpose=f"figure-storyboard-{artifact_name}",
        schema=STORYBOARD_REVIEW_SCHEMA, image_paths=paths,
        timeout_seconds=360.0,
    )
    review = json.loads(response.text)
    identities = {item["id"] for item in storyboard["candidates"]}
    if review.get("selected_id") not in identities:
        raise ValueError("storyboard visual reviewer selected an unknown candidate")
    updated = dict(storyboard)
    updated.update({
        "selected_id": review["selected_id"],
        "selection_reason": str(review["selection_reason"]),
        "selected_by": "native-image-layout-reviewer-v1",
        "visual_review": review, "visual_review_trace_path": response.trace_path,
        "candidate_images": [str(path.relative_to(root)) for path in paths],
        "candidate_images_sha256": {
            path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in paths
        },
    })
    atomic_write_json(Path(storyboard["path"]), {key: value for key, value in updated.items() if key != "path"})
    return {**updated, "path": storyboard["path"]}
