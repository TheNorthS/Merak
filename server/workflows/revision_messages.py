"""Researcher-facing explanations for deterministic revision findings."""

from __future__ import annotations

import re


def humanize_revision_issue(issue: str) -> str:
    """Translate one validator finding without changing its technical record."""
    clean = " ".join(str(issue or "").split())
    patterns = (
        (
            r"^([^:]+): missing declared symbol\(s\) in ([^:]+): (.+)$",
            "检查项 {0} 声明代码文件 {1} 应提供 {2}，但静态校验没有识别到这些可执行定义。"
            "需要确认实现名称、定义位置和方法契约是否一致。",
        ),
        (
            r"^([^:]+): missing config key\(s\) in ([^:]+): (.+)$",
            "检查项 {0} 需要配置文件 {1} 中的 {2}，但当前解析结果没有找到。"
            "后续实验可能无法按声明的设置运行。",
        ),
        (
            r"^([^:]+): missing declared anchor\(s\) in ([^:]+): (.+)$",
            "检查项 {0} 在 {1} 中没有找到用于证明实现存在的关键代码片段：{2}。",
        ),
    )
    for pattern, template in patterns:
        match = re.match(pattern, clean, flags=re.IGNORECASE)
        if match:
            return template.format(*match.groups())
    lowered = clean.casefold()
    messages = (
        (("research depth contract failed",),
         "当前产物可能已经生成文件，但核心假设、实现证据或证伪设计仍不完整，暂时不能支撑后续实验。"),
        (("no current metric file", "no machine-readable scientific metric"),
         "系统没有找到由成功实验运行产生并可追溯的指标文件；当前不能生成或引用结果型图表。"),
        (("at least two comparable methods",),
         "现有结果没有在同一数据划分和指标下覆盖至少两个可比较方法，无法形成有效的主比较。"),
        (("not referenced in prose",),
         "论文中已经插入图表，但正文没有引用并解释它；该图表尚未参与科研论证。"),
        (("idea_contract_sha256",),
         "实验方法契约与已经确认的研究 Idea 版本不一致，需要重新对齐后才能继续。"),
        (("experiment code integrity failed", "python syntax error"),
         "实验代码或配置无法被静态解析；当前产物不能安全执行。请先修复语法或配置错误。"),
        (("missing or empty", "file not found"),
         "验收所需的标准研究产物缺失或为空，当前节点还没有形成可审计的交付物。"),
        (("does not bind the accepted top-1 idea",),
         "当前实验或论文产物没有明确绑定已经确认的 Top-1 Idea，存在研究目标漂移风险。"),
    )
    for markers, message in messages:
        if any(marker in lowered for marker in markers):
            return message
    return f"独立验收仍发现一项未解决问题：{clean}"
