---
name: paper-figure
description: "Generate publication-quality figures and tables from experiment results. Use when user says \"画图\", \"作图\", \"generate figures\", \"paper figures\", or needs plots for a paper."
argument-hint: [figure-plan-or-data-path]
allowed-tools: Bash(*), Read, Write, Edit, Grep, Glob, generate_figure, figure_manifest, Skill, reviewer_api, reviewer_api_reply
---

# Paper Figure: Multi-Backend Publication Figure Orchestrator

Generate all figures and tables for a paper based on: **$ARGUMENTS**

## MERAK Native Multi-Backend Workflow

`paper-figure` owns the complete figure stage. Read
`figures/SCIENTIFIC_ASSET_PLAN.json` and `figures/FIGURE_SPECS.json`; route each
semantic asset by its declared `recommended_backend` and `recommended_skill`.
Do not replace the route with one preferred drawing style.

| Scientific asset | Backend | Executable skill |
|---|---|---|
| Quantitative results, ablations, robustness, calibration, scaling | Python / Matplotlib | `/paper-figure` |
| Paper-facing method/model architecture or conceptual mechanism (Phase 2b default) | Model-authored rich SVG | `/rich-svg-figure` |
| Simple formal workflow asset | FigureSpec JSON → SVG | `/figure-spec` |
| Explicit freeform-sketch override | Excalidraw | `/excalidraw-skill` |
| Explicit systems-editor override | Draw.io | `/figure-spec` |
| Simple protocol, participant/sample flow, state, or sequence | Mermaid | `/mermaid-diagram` |
| Formal algorithm, theorem, proof dependency, or equation structure | TikZ | `/paper-figure` |
| Explicit Phase-2b image mode, or auto-routed naturalistic illustration that code-native graphics cannot express | Image backend | `/paper-illustration` |

For a specialist route, invoke its complete skill with the `Skill` tool once and
group all assets for that backend into the same bounded request. A specialist is
not considered applied merely because its name appears in this policy. The
runtime records the actual invoking skill on every manifest entry, and the gate
rejects a backend or skill mismatch.

Every code-native asset must be passed through `generate_figure` with complete
project-grounded code and its stable `FIGURE_SPECS` id. Preserve `.py`, rich
`.svg`, FigureSpec `.json`, `.excalidraw`, `.drawio`, `.mmd`, or `.tex` source, a paper-usable render, and a
PNG preview where supported. Generated images must preserve `.prompt.json`.
Finish with `figure_manifest`. Generate one primary backend per semantic asset;
do not create parallel Mermaid/Draw.io/Excalidraw versions of the same idea.

The scientific asset contract is authoritative over any domain style preset.
A preset may choose layout, glyphs, or palette, but must never replace the
registered methods, ablations, stress axes, datasets, endpoints, or uncertainty
fields with stock examples. Preserve each paper-facing asset's stable label,
caption, scientific question, source-data paths, and claim links so the paper
writer cites and interprets the exact rendered evidence.

When the asset plan reports `quantitative_figure_policy: skip_without_real_metrics`,
skip every result, ablation, robustness, calibration, scaling, and comparison plot.
Do not create synthetic/watermarked plot previews. Continue only with the
configured Phase-2b route; its default for method architecture is model-authored rich SVG.

## Scope

| Category | Automated path | Examples |
|---|---|---|
| **Data-driven plots** | Python / Matplotlib | Curves, intervals, distributions, heatmaps |
| **Comparison tables** | LaTeX | Main results, ablations, prior-work comparisons |
| **Multi-panel figures** | Python plus LaTeX composition | Dataset, cohort, or condition panels |
| **Architecture/pipeline diagrams** | Routed specialist | Excalidraw, Draw.io, Mermaid, or TikZ |
| **Generated qualitative outputs** | Preserve actual model outputs | Sample grids and case studies |
| **Generated illustrations** | Explicit Phase-2b image mode, or auto route only when justified | Method overview, anatomy, apparatus, or spatial context |

## Constants

- **STYLE = `publication`** — Visual style preset. Options: `publication` (default, clean for print), `poster` (larger fonts), `slide` (bold colors)
- **DPI = 300** — Output resolution
- **FORMAT = `pdf`** — Output format. Options: `pdf` (vector, best for LaTeX), `png` (raster fallback)
- **COLOR_PALETTE = `tab10`** — Default matplotlib color cycle. Options: `tab10`, `Set2`, `colorblind` (deuteranopia-safe)
- **FONT_SIZE = 10** — Base font size (matches typical conference body text)
- **FIG_DIR = `figures/`** — Output directory for generated figures
- **REVIEWER_MODEL = `gpt-5.5`** — Model used via Reviewer API for figure quality review.

## Inputs

1. **paper/PAPER_PLAN.md** — canonical figure plan table (from `/paper-plan`)
2. **Experiment data** — JSON files, CSV files, or screen logs in `figures/` or project root
3. **Existing figures** — any manually created figures to preserve

If `paper/PAPER_PLAN.md` is missing, scan the accepted scientific asset contract and report the missing plan once; do not ask repeatedly or invent figures.

## Workflow

### Step 1: Read Figure Plan

Parse the Figure Plan table from paper/PAPER_PLAN.md:

```markdown
| ID | Type | Description | Data Source | Priority |
|----|------|-------------|-------------|----------|
| Fig 1 | Architecture | ... | experiments/src/model.py | HIGH |
| Fig 2 | Line plot | ... | experiments/results/metrics.csv | HIGH |
```

Identify:
- Which assets are quantitative and must be generated from real data
- Which specialist backend and skill each structured diagram declares
- Which are comparison tables and should be generated as LaTeX
- Which existing user-authored figures must be preserved rather than replaced

### Step 2: Set Up Plotting Environment

Create a shared style configuration script:

```python
# paper_plot_style.py — shared across all figure scripts
import matplotlib.pyplot as plt
import matplotlib
matplotlib.rcParams.update({
    'font.size': FONT_SIZE,
    'font.family': 'serif',
    'font.serif': ['Times New Roman', 'Times', 'DejaVu Serif'],
    'axes.labelsize': FONT_SIZE,
    'axes.titlesize': FONT_SIZE + 1,
    'xtick.labelsize': FONT_SIZE - 1,
    'ytick.labelsize': FONT_SIZE - 1,
    'legend.fontsize': FONT_SIZE - 1,
    'figure.dpi': DPI,
    'savefig.dpi': DPI,
    'savefig.bbox': 'tight',
    'savefig.pad_inches': 0.05,
    'axes.grid': False,
    'axes.spines.top': False,
    'axes.spines.right': False,
    'text.usetex': False,  # set True if LaTeX is available
    'mathtext.fontset': 'stix',
})

# Color palette
COLORS = plt.cm.tab10.colors  # or Set2, or colorblind-safe

def save_fig(fig, name, fmt=FORMAT):
    """Save figure to FIG_DIR with consistent naming."""
    fig.savefig(f'{FIG_DIR}/{name}.{fmt}')
    print(f'Saved: {FIG_DIR}/{name}.{fmt}')
```

### Step 3: Auto-Select Figure Type

Use this decision tree for data-driven figures (inspired by Imbad0202/academic-research-skills):

| Data Pattern | Recommended Type | Size |
|-------------|-----------------|------|
| X=time/steps, Y=metric | Line plot | 0.48\textwidth |
| Methods × 1 metric | Bar chart | 0.48\textwidth |
| Methods × multiple metrics | Grouped bar / radar | 0.95\textwidth |
| Two continuous variables | Scatter plot | 0.48\textwidth |
| Matrix / grid values | Heatmap | 0.48\textwidth |
| Distribution comparison | Box/violin plot | 0.48\textwidth |
| Multi-dataset results | Multi-panel (subfigure) | 0.95\textwidth |
| Prior work comparison | LaTeX table | — |

### Step 4: Generate Each Figure

For each figure in the plan, create a standalone Python script:

**Line plots** (training curves, scaling):
```python
# gen_fig2_training_curves.py
from paper_plot_style import *
import json

with open('figures/exp_results.json') as f:
    data = json.load(f)

fig, ax = plt.subplots(1, 1, figsize=(5, 3.5))
ax.plot(data['steps'], data['fac_loss'], label='Factorized', color=COLORS[0])
ax.plot(data['steps'], data['crf_loss'], label='CRF-LR', color=COLORS[1])
ax.set_xlabel('Training Steps')
ax.set_ylabel('Cross-Entropy Loss')
ax.legend(frameon=False)
save_fig(fig, 'fig2_training_curves')
```

**Bar charts** (comparison, ablation):
```python
fig, ax = plt.subplots(1, 1, figsize=(5, 3))
methods = ['Baseline', 'Method A', 'Method B', 'Ours']
values = [82.3, 85.1, 86.7, 89.2]
bars = ax.bar(methods, values, color=[COLORS[i] for i in range(len(methods))])
ax.set_ylabel('Accuracy (%)')
# Add value labels on bars
for bar, val in zip(bars, values):
    ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.3,
            f'{val:.1f}', ha='center', va='bottom', fontsize=FONT_SIZE-1)
save_fig(fig, 'fig3_comparison')
```

**Comparison tables** (LaTeX, for theory papers):
```latex
\begin{table}[t]
\centering
\caption{Comparison of estimation error bounds. $n$: sample size, $D$: ambient dim, $d$: latent dim, $K$: subspaces, $n_k$: modes.}
\label{tab:bounds}
\begin{tabular}{lccc}
\toprule
Method & Rate & Depends on $D$? & Multi-modal? \\
\midrule
\citet{MinimaxOkoAS23} & $n^{-s'/D}$ & Yes (curse) & No \\
\citet{ScoreMatchingdistributionrecovery} & $n^{-2/d}$ & No & No \\
\textbf{Ours} & $\sqrt{\sum n_k d_k / n}$ & No & Yes \\
\bottomrule
\end{tabular}
\end{table}
```

**Architecture/pipeline diagrams** (ROUTED — specialist-owned):
- Invoke `/excalidraw-skill`, `/figure-spec`, or `/mermaid-diagram` according to the specification.
- Keep the specialist's editable source and use the native renderer output in LaTeX.
- Use TikZ directly only for LaTeX-native mathematical or formal structures.
- Preserve user-authored figures unless the plan explicitly requests an in-place revision.

### Step 5: Run All Scripts

```bash
# Run all figure generation scripts
for script in gen_fig*.py; do
    python "$script"
done
```

Verify all output files exist and are non-empty.

### Step 6: Generate LaTeX Include Snippets

For each figure, output the LaTeX code to include it:

```latex
% === Fig 2: Training Curves ===
\begin{figure}[t]
    \centering
    \includegraphics[width=0.48\textwidth]{figures/fig2_training_curves.pdf}
    \caption{Training curves comparing factorized and CRF-LR denoising.}
    \label{fig:training_curves}
\end{figure}
```

Save all snippets to `figures/latex_includes.tex` for easy copy-paste into the paper.

### Step 7: Figure Quality Review with REVIEWER_MODEL

Send figure descriptions and captions to GPT-5.5 for review:

```
reviewer_api:
  model: gpt-5.5
  config: {"model_reasoning_effort": "xhigh"}
  prompt: |
    Review these figure/table plans for a [VENUE] submission.

    For each figure:
    1. Is the caption informative and self-contained?
    2. Does the figure type match the data being shown?
    3. Is the comparison fair and clear?
    4. Any missing baselines or ablations?
    5. Would a different visualization be more effective?

    [list all figures with captions and descriptions]
```

### Step 8: Quality Checklist

Before finishing, verify each figure (from pedrohcgs/claude-code-my-workflow):

- [ ] Font size readable at printed paper size (not too small)
- [ ] Colors distinguishable in grayscale (print-friendly)
- [ ] **No title inside figures** — titles go only in LaTeX `\caption{}` (from pedrohcgs)
- [ ] Legend does not overlap data
- [ ] Axis labels have units where applicable
- [ ] Axis labels are publication-quality (not variable names like `emp_rate`)
- [ ] Figure width fits single column (0.48\textwidth) or full width (0.95\textwidth)
- [ ] PDF output is vector (not rasterized text)
- [ ] No matplotlib default title (remove `plt.title` for publications)
- [ ] Serif font matches paper body text (Times / Computer Modern)
- [ ] Colorblind-accessible (if using colorblind palette)

## Output

```
figures/
├── paper_plot_style.py          # shared style config
├── gen_fig1_architecture.py     # per-figure scripts
├── gen_fig2_training_curves.py
├── gen_fig3_comparison.py
├── fig1_architecture.pdf        # generated figures
├── fig2_training_curves.pdf
├── fig3_comparison.pdf
├── latex_includes.tex           # LaTeX snippets for all figures
└── TABLE_*.tex                  # standalone table LaTeX files
```

## Key Rules

- **Every figure must be reproducible** — save the generation script alongside the output
- **Do NOT hardcode data** — always read from JSON/CSV files
- **Use vector format (PDF)** for all plots — PNG only as fallback
- **No decorative elements** — no background colors, no 3D effects, no chart junk
- **Consistent style across all figures** — same fonts, colors, line widths
- **Colorblind-safe** — verify with https://davidmathlogic.com/colorblind/ if needed
- **One script per figure** — easy to re-run individual figures when data changes
- **No titles inside figures** — captions are in LaTeX only
- **Comparison tables count as figures** — generate them as standalone .tex files

## Figure Type Reference

| Type | When to Use | Typical Size |
|------|------------|--------------|
| Line plot | Training curves, scaling trends | 0.48\textwidth |
| Bar chart | Method comparison, ablation | 0.48\textwidth |
| Grouped bar | Multi-metric comparison | 0.95\textwidth |
| Scatter plot | Correlation analysis | 0.48\textwidth |
| Heatmap | Attention, confusion matrix | 0.48\textwidth |
| Box/violin | Distribution comparison | 0.48\textwidth |
| Architecture | System overview | 0.95\textwidth |
| Multi-panel | Combined results (subfigures) | 0.95\textwidth |
| Comparison table | Prior bounds vs. ours (theory) | full width |

## Acknowledgements

Design pattern (type × style matrix) inspired by [baoyu-skills](https://github.com/jimliu/baoyu-skills). Publication style defaults and figure rules from [pedrohcgs/claude-code-my-workflow](https://github.com/pedrohcgs/claude-code-my-workflow). Visualization decision tree from [Imbad0202/academic-research-skills](https://github.com/Imbad0202/academic-research-skills).
