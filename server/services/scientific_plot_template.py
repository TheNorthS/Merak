"""Standalone source template for field-adaptive scientific plots."""

SCIENTIFIC_PLOT_TEMPLATE = r'''from pathlib import Path
import csv
import math
import textwrap
from collections import defaultdict
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

SCIENTIFIC_CONTEXT = __SCIENTIFIC_CONTEXT__
PUBLICATION_STYLE = __PUBLICATION_STYLE__
PLOT_TYPE = __PLOT_TYPE__
METRIC = __METRIC__
CURVE_PLOTS = __CURVE_PLOTS__
INTERVAL_PLOTS = __INTERVAL_PLOTS__

plt.rcParams.update({
    "font.family": PUBLICATION_STYLE["font_family"],
    "font.size": PUBLICATION_STYLE["font_size"],
    "axes.labelsize": PUBLICATION_STYLE["font_size"],
    "axes.titlesize": PUBLICATION_STYLE["font_size"] + 1,
    "xtick.labelsize": max(9, PUBLICATION_STYLE["font_size"] - 1),
    "ytick.labelsize": max(9, PUBLICATION_STYLE["font_size"] - 1),
    "legend.fontsize": max(9, PUBLICATION_STYLE["font_size"] - 1),
    "legend.frameon": False,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.grid": False,
    "pdf.fonttype": 42,
    "ps.fonttype": 42,
    "svg.fonttype": "none",
})

ROOT = Path(__file__).resolve().parents[2]
with (ROOT / __DATA_PATH__).open("r", encoding="utf-8-sig", newline="") as handle:
    rows = list(csv.DictReader(handle))
if not rows:
    raise RuntimeError("The registered scientific asset has no data rows.")

colors = PUBLICATION_STYLE["palette"]

def number(value, default=float("nan")):
    try:
        parsed = float(str(value).strip())
    except (TypeError, ValueError):
        return default
    return parsed if math.isfinite(parsed) else default

def wrapped(value, width=25):
    return "\n".join(textwrap.wrap(str(value or ""), width=width))

def interval_plot(plot_rows):
    usable = [row for row in plot_rows if math.isfinite(number(row.get("mean")))]
    if not usable:
        raise RuntimeError("Interval plot requires a numeric mean column.")
    labels = []
    for row in usable:
        condition = str(row.get("condition_value") or "").strip()
        label = str(row.get("method") or row.get("label") or "Estimate")
        labels.append(wrapped(f"{label} | {condition}" if condition else label))
    means = [number(row.get("mean")) for row in usable]
    lows = [number(row.get("ci95_low"), mean) for row, mean in zip(usable, means)]
    highs = [number(row.get("ci95_high"), mean) for row, mean in zip(usable, means)]
    order = sorted(range(len(usable)), key=lambda index: means[index])
    usable = [usable[index] for index in order]
    labels = [labels[index] for index in order]
    means = [means[index] for index in order]
    lows = [lows[index] for index in order]
    highs = [highs[index] for index in order]
    y = list(range(len(usable)))
    fig, ax = plt.subplots(figsize=(7.2, max(2.5, 0.48 * len(usable) + 0.8)))
    for index, (mean, low, high) in enumerate(zip(means, lows, highs)):
        ax.errorbar(
            mean,
            index,
            xerr=[[max(0.0, mean - low)], [max(0.0, high - mean)]],
            fmt="o",
            markersize=5.5,
            capsize=2.5,
            linewidth=1.15,
            color=colors[index % len(colors)],
            markeredgecolor="white",
            markeredgewidth=0.55,
        )
    ratio_metric = any(
        token in METRIC.casefold()
        for token in ("hazard ratio", "odds ratio", "risk ratio", "relative risk")
    )
    if ratio_metric and all(value > 0 for value in [*lows, *highs]):
        ax.axvline(1.0, color="#6B7280", linewidth=0.8, linestyle="--", zorder=0)
        if max(highs) / max(min(lows), 1e-12) > 20:
            ax.set_xscale("log")
    elif min(lows) < 0 < max(highs):
        ax.axvline(0.0, color="#6B7280", linewidth=0.8, linestyle="--", zorder=0)
    ax.set_yticks(y, labels)
    ax.set_xlabel(METRIC)
    ax.set_ylabel("")
    ax.tick_params(axis="y", length=0, pad=3)
    ax.tick_params(axis="x", length=3, width=0.7)
    ax.spines["left"].set_visible(False)
    ax.spines["bottom"].set_linewidth(0.7)
    span = max(highs) - min(lows)
    ax.set_xlim(min(lows) - 0.08 * (span or 1.0), max(highs) + 0.24 * (span or 1.0))
    for index, (mean, row) in enumerate(zip(means, usable)):
        n = str(row.get("n") or "").strip()
        suffix = f" (n={n})" if n else ""
        ax.annotate(
            f"{mean:.3g}{suffix}",
            (mean, index),
            xytext=(7, 0),
            textcoords="offset points",
            va="center",
            fontsize=max(9, PUBLICATION_STYLE["font_size"] - 1),
        )
    return fig, ax

def curve_plot(plot_rows):
    grouped = defaultdict(list)
    for index, row in enumerate(plot_rows):
        y = number(row.get("mean"))
        if not math.isfinite(y):
            continue
        x = number(row.get("condition_value"))
        if not math.isfinite(x):
            x = number(row.get("x_value"))
        if not math.isfinite(x):
            x = float(index)
        grouped[str(row.get("method") or "Estimate")].append((x, y, row))
    if not grouped:
        return interval_plot(plot_rows)
    distinct_x = {item[0] for values in grouped.values() for item in values}
    if len(distinct_x) < 2:
        return interval_plot(plot_rows)
    fig, ax = plt.subplots(figsize=(7.2, 4.1))
    for group_index, (method, values) in enumerate(sorted(grouped.items())):
        values = sorted(values, key=lambda item: item[0])
        xs = [item[0] for item in values]
        ys = [item[1] for item in values]
        lows = [number(item[2].get("ci95_low"), item[1]) for item in values]
        highs = [number(item[2].get("ci95_high"), item[1]) for item in values]
        color = colors[group_index % len(colors)]
        ax.plot(xs, ys, marker="o", markersize=4.2, linewidth=1.35, color=color, label=method)
        if any(abs(high - low) > 1e-12 for low, high in zip(lows, highs)):
            ax.fill_between(xs, lows, highs, color=color, alpha=0.14, linewidth=0)
    condition_names = [
        str(row.get("condition_name") or "").strip() for row in plot_rows
        if str(row.get("condition_name") or "").strip()
    ]
    ax.set_xlabel(condition_names[0].replace("_", " ").title() if condition_names else "Registered condition")
    ax.set_ylabel(METRIC)
    if PLOT_TYPE == "calibration":
        bounds = [number(row.get("condition_value")) for row in plot_rows]
        bounds += [number(row.get("mean")) for row in plot_rows]
        bounds = [value for value in bounds if math.isfinite(value)]
        if bounds:
            low, high = min(bounds), max(bounds)
            ax.plot([low, high], [low, high], color="#6B7280", linestyle="--", linewidth=0.8, label="Ideal")
    ax.legend(loc="best")
    ax.tick_params(length=3, width=0.7)
    return fig, ax

def replicate_plot(plot_rows):
    values_by_label = []
    for row in plot_rows:
        raw = [
            number(value)
            for value in str(row.get("raw_values") or "").split(";")
            if str(value).strip()
        ]
        raw = [value for value in raw if math.isfinite(value)]
        if not raw and math.isfinite(number(row.get("mean"))):
            raw = [number(row.get("mean"))]
        if raw:
            values_by_label.append((str(row.get("method") or "Condition"), raw, row))
    if not values_by_label:
        return interval_plot(plot_rows)
    fig, ax = plt.subplots(figsize=(7.2, max(3.0, 0.5 * len(values_by_label) + 1.2)))
    for index, (label, raw, row) in enumerate(values_by_label):
        offsets = [((position % 7) - 3) * 0.025 for position in range(len(raw))]
        ax.scatter(
            [index + offset for offset in offsets],
            raw,
            s=18,
            alpha=0.72,
            color=colors[index % len(colors)],
            edgecolors="white",
            linewidths=0.35,
        )
        mean = sum(raw) / len(raw)
        ax.plot([index - 0.22, index + 0.22], [mean, mean], color="#222222", linewidth=1.25)
    ax.set_xticks(range(len(values_by_label)), [wrapped(item[0], 18) for item in values_by_label])
    ax.set_ylabel(METRIC)
    ax.set_xlabel("")
    ax.tick_params(length=3, width=0.7)
    return fig, ax

def pathway_plot(plot_rows):
    usable = [row for row in plot_rows if math.isfinite(number(row.get("mean")))]
    if not usable:
        return interval_plot(plot_rows)
    significance = any(token in METRIC.casefold() for token in ("fdr", "q value", "adjusted p", "p value"))
    scored = []
    for row in usable:
        value = number(row.get("mean"))
        score = -math.log10(max(value, 1e-300)) if significance else value
        scored.append((score, row))
    scored = sorted(scored, key=lambda item: item[0], reverse=True)[:20][::-1]
    fig, ax = plt.subplots(figsize=(7.2, max(3.0, 0.34 * len(scored) + 1.0)))
    labels = [wrapped(item[1].get("method") or item[1].get("condition_value") or "Pathway", 30) for item in scored]
    values = [item[0] for item in scored]
    ax.barh(range(len(scored)), values, color=colors[0], height=0.68)
    ax.set_yticks(range(len(scored)), labels)
    ax.set_xlabel("-log10(adjusted P)" if significance else METRIC)
    ax.set_ylabel("")
    ax.tick_params(axis="y", length=0)
    return fig, ax

def tradeoff_plot(plot_rows):
    usable = [
        row for row in plot_rows
        if math.isfinite(number(row.get("mean")))
        and math.isfinite(number(row.get("secondary_mean")))
    ]
    if len(usable) < 2:
        return interval_plot(plot_rows)
    fig, ax = plt.subplots(figsize=(6.6, 4.4))
    for index, row in enumerate(usable):
        x = number(row.get("secondary_mean"))
        y = number(row.get("mean"))
        ax.scatter(
            x,
            y,
            s=38,
            color=colors[index % len(colors)],
            edgecolors="white",
            linewidths=0.55,
            zorder=3,
        )
        ax.annotate(
            wrapped(row.get("method") or "Configuration", 16),
            (x, y),
            xytext=(5, 4),
            textcoords="offset points",
            fontsize=max(9, PUBLICATION_STYLE["font_size"] - 1),
        )
    secondary_metric = str(usable[0].get("secondary_metric") or "Secondary endpoint")
    ax.set_xlabel(secondary_metric)
    ax.set_ylabel(METRIC)
    ax.tick_params(length=3, width=0.7)
    return fig, ax

def volcano_plot(plot_rows):
    usable = []
    for row in plot_rows:
        effect = number(row.get("mean"))
        adjusted = number(row.get("adjusted_p"))
        if not math.isfinite(adjusted):
            adjusted = number(row.get("secondary_mean"))
        if math.isfinite(effect) and math.isfinite(adjusted) and adjusted > 0:
            usable.append((effect, -math.log10(max(adjusted, 1e-300)), row))
    if len(usable) < 3:
        return pathway_plot(plot_rows)
    fig, ax = plt.subplots(figsize=(6.6, 4.5))
    threshold = -math.log10(0.05)
    for index, (effect, significance, row) in enumerate(usable):
        highlighted = significance >= threshold
        ax.scatter(
            effect,
            significance,
            s=24 if highlighted else 15,
            color=colors[index % len(colors)] if highlighted else "#9CA3AF",
            alpha=0.86 if highlighted else 0.58,
            edgecolors="none",
        )
    ax.axhline(threshold, color="#6B7280", linestyle="--", linewidth=0.8)
    ax.axvline(0.0, color="#6B7280", linestyle=":", linewidth=0.7)
    ax.set_xlabel(METRIC)
    ax.set_ylabel("-log10(adjusted P)")
    ax.tick_params(length=3, width=0.7)
    return fig, ax

def phase_plot(plot_rows):
    usable = [
        row for row in plot_rows
        if math.isfinite(number(row.get("condition_value")))
        and math.isfinite(number(row.get("secondary_mean")))
        and math.isfinite(number(row.get("mean")))
    ]
    if len(usable) < 3:
        return curve_plot(plot_rows)
    fig, ax = plt.subplots(figsize=(6.4, 4.6))
    scatter = ax.scatter(
        [number(row.get("condition_value")) for row in usable],
        [number(row.get("secondary_mean")) for row in usable],
        c=[number(row.get("mean")) for row in usable],
        cmap="viridis",
        s=38,
        edgecolors="white",
        linewidths=0.4,
    )
    ax.set_xlabel(str(usable[0].get("condition_name") or "Registered parameter").replace("_", " ").title())
    ax.set_ylabel(str(usable[0].get("secondary_metric") or "Secondary parameter"))
    fig.colorbar(scatter, ax=ax, label=METRIC, fraction=0.04, pad=0.025)
    return fig, ax

def evidence_matrix(plot_rows):
    themes = list(dict.fromkeys(str(row.get("theme") or "Uncoded") for row in plot_rows))
    cases = list(dict.fromkeys(str(row.get("case") or row.get("source_id") or "Source") for row in plot_rows))
    matrix = [[0 for _ in cases] for _ in themes]
    for row in plot_rows:
        matrix[themes.index(str(row.get("theme") or "Uncoded"))][
            cases.index(str(row.get("case") or row.get("source_id") or "Source"))
        ] += 1
    fig, ax = plt.subplots(figsize=(max(5.0, 0.55 * len(cases) + 2.0), max(3.0, 0.42 * len(themes) + 1.5)))
    image = ax.imshow(matrix, cmap="Blues", aspect="auto", interpolation="nearest")
    ax.set_xticks(range(len(cases)), [wrapped(value, 14) for value in cases], rotation=35, ha="right")
    ax.set_yticks(range(len(themes)), [wrapped(value, 22) for value in themes])
    ax.set_xlabel("Case or evidence source")
    ax.set_ylabel("Theme")
    for row_index, values in enumerate(matrix):
        for column_index, value in enumerate(values):
            if value:
                ax.text(column_index, row_index, str(value), ha="center", va="center", fontsize=7)
    fig.colorbar(image, ax=ax, label="Coded evidence records", fraction=0.035, pad=0.025)
    return fig, ax

if PLOT_TYPE in {"evidence_matrix", "theme_map", "case_comparison"} and "theme" in rows[0]:
    fig, ax = evidence_matrix(rows)
elif PLOT_TYPE in {"replicate_distribution"}:
    fig, ax = replicate_plot(rows)
elif PLOT_TYPE == "volcano_effect":
    fig, ax = volcano_plot(rows)
elif PLOT_TYPE == "pathway_enrichment":
    fig, ax = pathway_plot(rows)
elif PLOT_TYPE == "tradeoff_frontier":
    fig, ax = tradeoff_plot(rows)
elif PLOT_TYPE == "phase_diagram":
    fig, ax = phase_plot(rows)
elif PLOT_TYPE in CURVE_PLOTS:
    fig, ax = curve_plot(rows)
else:
    fig, ax = interval_plot(rows)

fig.tight_layout(pad=0.65)
'''
