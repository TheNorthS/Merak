"""Evidence-bounded scientific narrative authoring request."""

from pathlib import Path
from typing import Any, Callable


def narrative_authoring_prompt(
    *, project_path: str, direction: str, options: dict[str, Any],
    paths: dict[str, str], inventory_builder: Callable[..., str],
) -> str:
    mode = str(options.get('non_experiment_evidence_mode') or 'design_only').casefold()
    boundary = (
        '当前使用确定性生成的场景记录。哈希绑定只证明记录身份，不证明生成机制具有科学有效性。'
        '如生成器只构造标签化表格而未执行模型，数值排序只能作为该生成场景的描述性观察；'
        '不得将其称为真实模型优劣、机制成立或研究假设被证伪的证据。'
        '逐项区分可核对的描述事实与仍待验证的科学主张，保留不利排序、证据缺口和未来证伪路径；'
        '允许科学主张保持待验证，不得为满足流程而强行赋予支持或反驳结论。'
        if mode == 'synthetic_preview' else
        '没有运行或导入证据的结论必须保持计划态；不得把实验设计、实现完整性或文件存在改写成实证支持。'
    )
    sources = [
        paths['selected_idea_contract'], paths['novelty_report'],
        str(Path(project_path) / 'experiments/METHOD_CONTRACT.json'),
        str(Path(project_path) / 'experiments/EXPERIMENT_PLAN.md'),
        str(Path(project_path) / 'experiments/results/analysis.md'),
        str(Path(project_path) / 'figures/SCIENTIFIC_ASSET_PLAN.json'),
        str(Path(project_path) / 'paper/PAPER_PLAN.md'),
    ]
    inventory = inventory_builder(sources, limit=80)
    return f"""Build one coherent, evidence-bounded scientific narrative.

Research direction: {direction}
Evidence boundary: {boundary}

Authoritative inputs:
{inventory}

Write only `{project_path}/NARRATIVE_REPORT.md`. Read the frozen selected idea,
method contract and result analysis. Read a scientific asset plan or paper plan only
if listed in the existing inventory; the paper-plan delegate follows this narrative
and missing future figure/plan artifacts are not prerequisites for authoring it. For
every public claim, state the mechanism, decisive comparison, observed or
pending evidence, counterevidence, boundary conditions, and falsification rule.
Use publication-facing names from schema-2 publication semantics. Internal IDs,
paths, workflow status, and internal evidence-mode labels must not enter manuscript-facing prose.
Explain simulation data generation, fixed configurations and uncertainty honestly where relevant;
the Methods account and evidence boundary must remain scientifically reproducible.
Do not invent values or cite implementation
readiness as scientific evidence. The report organizes the argument followed
by paper sections; it must not draft LaTeX or replace the paper plan.
"""
