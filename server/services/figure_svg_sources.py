"""Deterministic SVG source templates and portability normalization."""

from __future__ import annotations

import re
from typing import Any

from .evaluation_design_svg import _evaluation_design_svg as _evaluation_design_svg


BENCHMARK_MAPPINGS = [
    {"element_id": "partitioned_data", "source_path": "experiments/src/data.py", "source_symbol": "load_data_contract", "semantic_role": "versioned input and protected partitions"},
    {"element_id": "input_projection", "source_path": "experiments/src/models.py", "source_symbol": "BenchmarkClassifier", "semantic_role": "residual model input projection"},
    {"element_id": "residual_stack", "source_path": "experiments/src/models.py", "source_symbol": "ResidualBlock", "semantic_role": "width-preserving residual stack"},
    {"element_id": "task_head", "source_path": "experiments/src/models.py", "source_symbol": "BenchmarkClassifier.task_head", "semantic_role": "binary classification head"},
    {"element_id": "probabilities", "source_path": "experiments/src/models.py", "source_symbol": "BenchmarkClassifier.forward", "semantic_role": "logits-to-probabilities path"},
    {"element_id": "calibration_branch", "source_path": "experiments/src/objectives.py", "source_symbol": "TemperatureCalibrator", "semantic_role": "calibration-only branch"},
    {"element_id": "linear_baseline", "source_path": "experiments/src/models.py", "source_symbol": "BenchmarkClassifier", "semantic_role": "linear reference path"},
    {"element_id": "mlp_baseline", "source_path": "experiments/src/models.py", "source_symbol": "BenchmarkClassifier", "semantic_role": "dense MLP reference path"},
    {"element_id": "matched_controls", "source_path": "experiments/src/models.py", "source_symbol": "validate_single_factor_protocol", "semantic_role": "matched single-factor controls"},
    {"element_id": "registered_outputs", "source_path": "experiments/src/evaluation.py", "source_symbol": "evaluate_final_partition", "semantic_role": "registered held-out endpoints"},
    {"element_id": "traceable_evidence", "source_path": "experiments/src/provenance.py", "source_symbol": "build_ledger_record", "semantic_role": "run-resolved evidence"},
]


def _benchmark_model_suite_svg(metadata: dict[str, Any]) -> tuple[str, list[dict[str, str]]]:
    """Build a paper-facing predictive architecture from the resolved model config."""
    blueprint = dict(metadata.get("architecture_blueprint") or {})
    config = dict(blueprint.get("model_configuration") or {})
    hidden = str(config.get("hidden_dim") or 256)
    depth = str(config.get("depth") or 3)
    classes = str(config.get("num_classes") or 2)
    expanded = str(int(hidden) * 2) if hidden.isdigit() else f"2×{hidden}"
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="1800" height="900" viewBox="0 0 1800 900">
<defs>
  <marker id="arrow" markerWidth="10" markerHeight="8" refX="9" refY="4" orient="auto"><path d="M0,0 L10,4 L0,8 Z" fill="#40546f"/></marker>
  <marker id="arrowTeal" markerWidth="10" markerHeight="8" refX="9" refY="4" orient="auto"><path d="M0,0 L10,4 L0,8 Z" fill="#0f8b78"/></marker>
  <filter id="shadow" x="-20%" y="-20%" width="140%" height="140%"><feDropShadow dx="0" dy="3" stdDeviation="5" flood-color="#203040" flood-opacity="0.12"/></filter>
</defs>
<rect width="1800" height="900" fill="#ffffff"/>
<text x="70" y="62" font-family="Helvetica,Arial,sans-serif" font-size="31" font-weight="700" fill="#16243a">Matched Predictive Models and Residual MLP Architecture</text>
<text x="70" y="94" font-family="Helvetica,Arial,sans-serif" font-size="16" fill="#607089">The focal residual path is expanded; linear and dense MLP references share the same data, budget, and prediction interface.</text>
<line x1="70" y1="118" x2="1730" y2="118" stroke="#d8e1ec" stroke-width="2"/>

<!-- data contract -->
<g id="partitioned_data" filter="url(#shadow)">
  <rect x="70" y="205" width="250" height="475" rx="22" fill="#eff6ff" stroke="#2f6fdf" stroke-width="2.5"/>
  <text x="95" y="245" font-family="Helvetica,Arial,sans-serif" font-size="15" font-weight="700" fill="#2f5fa8">DATA CONTRACT</text>
  <ellipse cx="195" cy="305" rx="82" ry="24" fill="#ffffff" stroke="#2f6fdf" stroke-width="2"/>
  <path d="M113 305v90c0 13 37 24 82 24s82-11 82-24v-90" fill="#dbeafe" stroke="#2f6fdf" stroke-width="2"/>
  <ellipse cx="195" cy="395" rx="82" ry="24" fill="#dbeafe" stroke="#2f6fdf" stroke-width="2"/>
  <text x="195" y="310" text-anchor="middle" font-family="Helvetica,Arial,sans-serif" font-size="18" font-weight="700" fill="#17243a">Versioned inputs</text>
  <text x="195" y="454" text-anchor="middle" font-family="Helvetica,Arial,sans-serif" font-size="14" fill="#52647b">features · labels · groups</text>
  <rect x="98" y="490" width="194" height="128" rx="14" fill="#ffffff" stroke="#7aa7e8" stroke-width="1.8"/>
  <text x="195" y="522" text-anchor="middle" font-family="Helvetica,Arial,sans-serif" font-size="17" font-weight="700" fill="#17243a">Protected partitions</text>
  <text x="120" y="555" font-family="Helvetica,Arial,sans-serif" font-size="14" fill="#52647b">Train / selection</text>
  <text x="120" y="580" font-family="Helvetica,Arial,sans-serif" font-size="14" fill="#52647b">Calibration / held-out</text>
  <path d="M112 595h166" stroke="#b9d1f2" stroke-width="2"/>
</g>

<!-- baselines -->
<rect x="365" y="155" width="1335" height="160" rx="20" fill="#f8fafc" stroke="#cbd5e1" stroke-width="2"/>
<text x="390" y="187" font-family="Helvetica,Arial,sans-serif" font-size="15" font-weight="700" fill="#596b82">MATCHED REFERENCE PATHS</text>
<g id="linear_baseline"><rect x="405" y="215" width="320" height="68" rx="13" fill="#ffffff" stroke="#8ca0b8" stroke-width="2"/><text x="430" y="244" font-family="Helvetica,Arial,sans-serif" font-size="18" font-weight="700" fill="#17243a">Linear reference</text><text x="430" y="268" font-family="Helvetica,Arial,sans-serif" font-size="14" fill="#607089">flatten → Linear({classes})</text></g>
<g id="mlp_baseline"><rect x="770" y="215" width="395" height="68" rx="13" fill="#eef8f6" stroke="#55a99b" stroke-width="2"/><text x="795" y="244" font-family="Helvetica,Arial,sans-serif" font-size="18" font-weight="700" fill="#17243a">Dense MLP reference</text><text x="795" y="268" font-family="Helvetica,Arial,sans-serif" font-size="14" fill="#607089">Linear({hidden}) → GELU → dense stack</text></g>
<path d="M320 260H405" stroke="#40546f" stroke-width="2.2" marker-end="url(#arrow)"/><path d="M320 280C500 325 650 240 770 250" fill="none" stroke="#40546f" stroke-width="2.2" marker-end="url(#arrow)"/>

<!-- focal architecture -->
<rect x="365" y="350" width="1335" height="390" rx="24" fill="#f4fbf9" stroke="#75bbae" stroke-width="2.5"/>
<text x="390" y="389" font-family="Helvetica,Arial,sans-serif" font-size="16" font-weight="700" fill="#0f766e">FOCAL RESIDUAL MLP</text>
<g id="input_projection" filter="url(#shadow)"><rect x="410" y="465" width="205" height="115" rx="17" fill="#ffffff" stroke="#0f8b78" stroke-width="2.5"/><text x="512" y="505" text-anchor="middle" font-family="Helvetica,Arial,sans-serif" font-size="19" font-weight="700" fill="#17243a">Input projection</text><text x="512" y="535" text-anchor="middle" font-family="Helvetica,Arial,sans-serif" font-size="14" fill="#607089">Linear(input, {hidden})</text><text x="512" y="559" text-anchor="middle" font-family="Helvetica,Arial,sans-serif" font-size="14" fill="#607089">GELU · Dropout</text></g>
<path d="M320 535H410" stroke="#0f8b78" stroke-width="3" marker-end="url(#arrowTeal)"/>
<g id="residual_stack">
  <rect x="665" y="420" width="545" height="210" rx="20" fill="#ffffff" stroke="#0f8b78" stroke-width="2.5"/>
  <text x="692" y="452" font-family="Helvetica,Arial,sans-serif" font-size="18" font-weight="700" fill="#17243a">Residual block × {depth}</text>
  <g id="residual_block_1"><rect x="700" y="490" width="88" height="62" rx="10" fill="#d7f0ea" stroke="#49a795"/><text x="744" y="527" text-anchor="middle" font-family="Helvetica,Arial,sans-serif" font-size="14" fill="#173f38">LayerNorm</text></g>
  <g id="residual_block_2"><rect x="820" y="490" width="92" height="62" rx="10" fill="#d7f0ea" stroke="#49a795"/><text x="866" y="517" text-anchor="middle" font-family="Helvetica,Arial,sans-serif" font-size="14" fill="#173f38">Linear</text><text x="866" y="538" text-anchor="middle" font-family="Helvetica,Arial,sans-serif" font-size="13" fill="#52647b">{hidden} → {expanded}</text></g>
  <g id="residual_activation"><rect x="944" y="490" width="88" height="62" rx="10" fill="#d7f0ea" stroke="#49a795"/><text x="988" y="517" text-anchor="middle" font-family="Helvetica,Arial,sans-serif" font-size="14" fill="#173f38">GELU</text><text x="988" y="538" text-anchor="middle" font-family="Helvetica,Arial,sans-serif" font-size="13" fill="#52647b">Dropout</text></g>
  <g id="residual_block_3"><rect x="1064" y="490" width="104" height="62" rx="10" fill="#d7f0ea" stroke="#49a795"/><text x="1116" y="517" text-anchor="middle" font-family="Helvetica,Arial,sans-serif" font-size="14" fill="#173f38">Linear</text><text x="1116" y="538" text-anchor="middle" font-family="Helvetica,Arial,sans-serif" font-size="13" fill="#52647b">{expanded} → {hidden}</text></g>
  <path d="M788 521H820M912 521H944M1032 521H1064" stroke="#0f8b78" stroke-width="2.2" marker-end="url(#arrowTeal)"/>
  <path d="M700 570C780 620 1080 620 1168 570" fill="none" stroke="#d97706" stroke-width="3" marker-end="url(#arrow)"/>
  <circle cx="1168" cy="570" r="15" fill="#fff4df" stroke="#d97706" stroke-width="2"/><text x="1168" y="576" text-anchor="middle" font-family="Helvetica,Arial,sans-serif" font-size="20" font-weight="700" fill="#9a5b0a">+</text>
  <text x="934" y="610" text-anchor="middle" font-family="Helvetica,Arial,sans-serif" font-size="14" font-weight="700" fill="#b66c0d">identity skip connection</text>
</g>
<path d="M615 522H665" stroke="#0f8b78" stroke-width="3" marker-end="url(#arrowTeal)"/>
<g id="task_head" filter="url(#shadow)"><rect x="1260" y="465" width="180" height="115" rx="17" fill="#fff1f5" stroke="#c33a65" stroke-width="2.5"/><text x="1350" y="505" text-anchor="middle" font-family="Helvetica,Arial,sans-serif" font-size="19" font-weight="700" fill="#17243a">Task head</text><text x="1350" y="535" text-anchor="middle" font-family="Helvetica,Arial,sans-serif" font-size="14" fill="#607089">Linear({hidden}, {classes})</text><text x="1350" y="559" text-anchor="middle" font-family="Helvetica,Arial,sans-serif" font-size="14" fill="#607089">class logits</text></g>
<path d="M1210 522H1260" stroke="#0f8b78" stroke-width="3" marker-end="url(#arrowTeal)"/>
<g id="probabilities"><rect x="1490" y="465" width="165" height="115" rx="17" fill="#fff8eb" stroke="#d97706" stroke-width="2.5"/><text x="1572" y="505" text-anchor="middle" font-family="Helvetica,Arial,sans-serif" font-size="19" font-weight="700" fill="#17243a">Probabilities</text><text x="1572" y="535" text-anchor="middle" font-family="Helvetica,Arial,sans-serif" font-size="14" fill="#607089">Softmax</text><text x="1572" y="559" text-anchor="middle" font-family="Helvetica,Arial,sans-serif" font-size="14" fill="#607089">held-out prediction</text></g>
<path d="M1440 522H1490" stroke="#c33a65" stroke-width="2.7" marker-end="url(#arrow)"/>
<g id="calibration_branch"><rect x="1260" y="645" width="395" height="62" rx="13" fill="#f5f0ff" stroke="#805ad5" stroke-width="2"/><text x="1285" y="675" font-family="Helvetica,Arial,sans-serif" font-size="16" font-weight="700" fill="#4d358d">Temperature calibration</text><text x="1285" y="696" font-family="Helvetica,Arial,sans-serif" font-size="13" fill="#607089">fit only on calibration partition · applied after logits</text></g>
<path d="M1350 580V645" stroke="#805ad5" stroke-width="2.2" marker-end="url(#arrow)"/>

<!-- bottom scientific contract -->
<g id="matched_controls"><rect x="410" y="785" width="410" height="72" rx="14" fill="#ffffff" stroke="#805ad5" stroke-width="2"/><text x="435" y="815" font-family="Helvetica,Arial,sans-serif" font-size="16" font-weight="700" fill="#17243a">Matched single-factor controls</text><text x="435" y="840" font-family="Helvetica,Arial,sans-serif" font-size="13" fill="#607089">architecture · recipe · calibration; shared data, budget, and seeds</text></g>
<g id="registered_outputs"><rect x="875" y="785" width="375" height="72" rx="14" fill="#ffffff" stroke="#2f6fdf" stroke-width="2"/><text x="900" y="815" font-family="Helvetica,Arial,sans-serif" font-size="16" font-weight="700" fill="#17243a">Registered held-out readouts</text><text x="900" y="840" font-family="Helvetica,Arial,sans-serif" font-size="13" fill="#607089">accuracy · shifted NLL/Brier · latency · peak memory</text></g>
<g id="traceable_evidence"><rect x="1305" y="785" width="350" height="72" rx="14" fill="#ffffff" stroke="#68798f" stroke-width="2"/><text x="1330" y="815" font-family="Helvetica,Arial,sans-serif" font-size="16" font-weight="700" fill="#17243a">Run-resolved evidence</text><text x="1330" y="840" font-family="Helvetica,Arial,sans-serif" font-size="13" fill="#607089">split · config · seed · prediction · device measurement</text></g>
<path d="M820 821H875M1250 821H1305" stroke="#68798f" stroke-width="2" stroke-dasharray="7 5" marker-end="url(#arrow)"/>
</svg>'''
    return svg, [dict(item) for item in BENCHMARK_MAPPINGS]




def _svg_add_attribute(tag: str, attribute: str) -> str:
    if tag.rstrip().endswith("/>"):
        closing_index = tag.rfind("/>")
        return tag[:closing_index].rstrip() + " " + attribute + "/>"
    closing_index = tag.rfind(">")
    return tag[:closing_index].rstrip() + " " + attribute + ">"


def _normalize_svg_marker_viewports(svg_text: str) -> str:
    """Make SVG arrow markers deterministic across Cairo/Chromium renderers.

    CairoSVG can magnify markers on curved paths when a marker has no explicit
    viewBox and inherits the SVG default ``strokeWidth`` coordinate system.
    Keep the model-authored path geometry, but bind its viewport to the declared
    marker dimensions and use fixed user-space units.
    """

    def normalize(match: re.Match[str]) -> str:
        tag = match.group(0)
        width_match = re.search(
            r'\bmarkerWidth\s*=\s*["\']([0-9]+(?:\.[0-9]+)?)["\']',
            tag,
            re.IGNORECASE,
        )
        height_match = re.search(
            r'\bmarkerHeight\s*=\s*["\']([0-9]+(?:\.[0-9]+)?)["\']',
            tag,
            re.IGNORECASE,
        )
        if not width_match or not height_match:
            return tag
        if re.search(r"\bmarkerUnits\s*=", tag, re.IGNORECASE):
            tag = re.sub(
                r'\bmarkerUnits\s*=\s*(["\']).*?\1',
                'markerUnits="userSpaceOnUse"',
                tag,
                flags=re.IGNORECASE,
            )
        else:
            tag = _svg_add_attribute(tag, 'markerUnits="userSpaceOnUse"')
        if not re.search(r"\bviewBox\s*=", tag, re.IGNORECASE):
            insertion = (
                f' viewBox="0 0 {width_match.group(1)} {height_match.group(1)}"'
            )
            tag = _svg_add_attribute(tag, insertion.strip())
        return tag

    return re.sub(r"<marker\b[^>]*>", normalize, svg_text, flags=re.IGNORECASE)


_VECTOR_STYLE_PROPERTIES = frozenset({
    "fill", "fill-opacity", "stroke", "stroke-width", "stroke-opacity",
    "stroke-linecap", "stroke-linejoin", "stroke-dasharray",
    "stroke-dashoffset", "marker-start", "marker-mid", "marker-end", "opacity",
})


def _vector_class_styles(svg_text: str) -> dict[str, dict[str, str]]:
    styles: dict[str, dict[str, str]] = {}
    for name, body in re.findall(r"\.([A-Za-z_][\w-]*)\s*\{([^}]*)\}", svg_text):
        declarations = {}
        for key, value in re.findall(r"([\w-]+)\s*:\s*([^;}{]+)", body):
            key = key.casefold()
            if key in _VECTOR_STYLE_PROPERTIES:
                declarations[key] = value.strip()
        if declarations:
            styles.setdefault(name, {}).update(declarations)
    return styles


def _inline_svg_vector_class_styles(svg_text: str) -> str:
    """Preserve model geometry while making vector CSS renderer-independent."""
    styles = _vector_class_styles(svg_text)
    if not styles:
        return svg_text

    def normalize(match: re.Match[str]) -> str:
        tag = match.group(0)
        class_match = re.search(r'\bclass\s*=\s*["\']([^"\']+)["\']', tag, re.I)
        if not class_match:
            return tag
        merged: dict[str, str] = {}
        for name in class_match.group(1).split():
            merged.update(styles.get(name, {}))
        for key, value in merged.items():
            if not re.search(rf"\b{re.escape(key)}\s*=", tag, re.I):
                tag = _svg_add_attribute(tag, f'{key}="{value}"')
        return tag

    return re.sub(
        r"<(?:path|line|polyline|polygon|circle|ellipse|rect)\b[^>]*>",
        normalize, svg_text, flags=re.IGNORECASE,
    )


def _raise_svg_connectors(svg_text: str) -> str:
    """Paint authored arrow connectors after nodes without changing geometry."""
    pattern = re.compile(
        r"<path\b(?=[^>]*\bmarker-end\s*=)[^>]*(?:/>|>\s*</path>)",
        re.IGNORECASE,
    )
    connectors = pattern.findall(svg_text)
    if not connectors:
        return svg_text
    body = pattern.sub("", svg_text)
    closing = body.lower().rfind("</svg>")
    if closing < 0:
        return svg_text
    layer = '<g data-runtime-layer="connectors">' + "".join(connectors) + "</g>"
    return body[:closing] + layer + body[closing:]

