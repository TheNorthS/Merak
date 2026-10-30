"""Shared context, persistence, and scope policies for the chat API."""

from __future__ import annotations

import asyncio
import time
from typing import Any

from fastapi import WebSocket

from ..agent import ModelRole, init_models_from_env
from ..agent.engine import RESEARCH_ARTIFACT_DIRS, RESEARCH_ARTIFACT_FILES
from ..agent.prompts import COPILOT_SYSTEM_PROMPT, get_system_prompt_for_command
from ..agent.tools import register_all_tools


_initialized = False
CHAT_HISTORY_FILE = "conversations.json"
MAX_CHAT_HISTORY_CONVERSATIONS = 50
MAX_CHAT_HISTORY_MESSAGES = 240
MAX_CHAT_MESSAGE_CHARS = 40000

CHAT_ARTIFACT_TOOLS = [
    "Read", "Write", "Edit", "Glob", "Grep",
    "arxiv_search", "semantic_scholar_search", "WebSearch", "WebFetch",
    "latex_compile", "generate_figure", "scaffold_paper", "verify_citation",
    "reviewer_api", "mcp__gemini-cli__search", "mcp__zotero__search",
    "mcp__obsidian-vault__read", "evidence_check", "provenance_stamp", "extract_paper_style",
]


CHAT_MODE_TOOLS = {
    "ask": [
        "Read",
        "arxiv_search", "semantic_scholar_search", "WebSearch", "WebFetch",
        "mcp__gemini-cli__search", "mcp__zotero__search", "mcp__obsidian-vault__read",
        "evidence_check", "extract_paper_style",
    ],
    "edit": CHAT_ARTIFACT_TOOLS,
    "review": [
        "Read", "Glob", "Grep",
        "semantic_scholar_search", "WebSearch", "WebFetch", "verify_citation",
        "reviewer_api", "mcp__gemini-cli__search", "mcp__zotero__search",
        "evidence_check", "extract_paper_style",
    ],
    "write": [
        "Read", "Write", "Edit", "Glob", "Grep",
        "arxiv_search", "semantic_scholar_search", "WebSearch", "WebFetch",
        "latex_compile", "scaffold_paper", "verify_citation",
        "mcp__gemini-cli__search", "mcp__zotero__search", "mcp__obsidian-vault__read",
        "evidence_check", "provenance_stamp", "extract_paper_style",
    ],
    "figure": [
        "Read", "Glob", "Grep", "generate_figure", "WebSearch", "WebFetch",
        "evidence_check", "provenance_stamp",
    ],
}

CHAT_MODE_PROMPTS = {
    "ask": "当前模式：Ask。只解释、分析和给建议，不修改文件。若上下文文件已经提供，直接基于上下文回答；只有用户要求定位关联配置/结果/引用时，才在研究产物目录内使用 Read/Glob/Grep。",
    "edit": "当前模式：Edit。可以精确修改研究产物文件，所有 Write/Edit 都只生成待审批变更提案。先定位最符合用户意图的研究产物，再用 Edit 做局部替换。",
    "review": "当前模式：Review。以严格科研审稿/代码审查视角指出问题和改进建议，不修改文件。可以在研究产物目录内读取/搜索证据。",
    "write": "当前模式：Write。可以起草或续写论文、实验说明、slides 内容和研究笔记；先利用上下文，再写入研究产物目录。",
    "figure": "当前模式：Figure。只生成或改进科研图表产物，输出目录应在 figures/。不要执行任意用户脚本。",
}

CHAT_MODE_ROLES = {
    "ask": ModelRole.GENERAL,
    "edit": ModelRole.EXECUTOR,
    "review": ModelRole.REVIEWER,
    "write": ModelRole.EXECUTOR,
    "figure": ModelRole.FIGURE,
}




class _SerializedChatSocket:
    """Serialize all writes emitted by the receive loop and background Agent.

    Starlette does not permit concurrent ``send_text`` calls on one WebSocket.
    The chat endpoint deliberately keeps receiving cancel/ping messages while
    an Agent streams events, so every existing call is routed through this
    connection-local lock instead of relying on each callback to coordinate.
    """

    def __init__(self, websocket: WebSocket) -> None:
        self._websocket = websocket
        self._send_lock = asyncio.Lock()

    async def receive_text(self) -> str:
        return await self._websocket.receive_text()

    async def send_text(self, payload: str) -> None:
        async with self._send_lock:
            await asyncio.wait_for(
                self._websocket.send_text(payload),
                timeout=10.0,
            )

CHAT_SCOPE_PROMPT = """

## Chat 面板范围

你只能调整 MERAK 生成或管理的研究产物：paper/、slides/、experiments/、figures/、literature/、ideas/，以及根目录 NARRATIVE_REPORT.md。
禁止读取、搜索或修改 IDE 自身源码和配置，例如项目根目录 src/、server/、electron/、package.json、README.md；但 experiments/src/ 属于实验代码产物，可以按用户指令处理。
允许使用 Glob/Grep 在上述研究产物目录内定位相关文件，例如 experiments/configs、experiments/src、paper、slides；不要扫描整个项目根目录。
如果用户要求调整训练参数、实验参数或预训练设置，优先定位并修改 YAML/JSON/TOML 配置文件；不要先改 Python 源码里的默认 fallback。只有找不到配置文件或用户明确要求改源码时，才考虑修改 experiments/src/。
在 Chat 面板中，Write/Edit 只会生成待审批变更提案；文件不会立即修改。提案必须由用户在界面中批准后才会写入。
"""

CHAT_ALIGNMENT_PROMPT = """

## 科研目标对齐

Chat 面板服务于 workflow 生成后的研究产物调整，而不是通用 IDE 源码助手。每次回答都要优先保持项目整体 idea、研究假设、贡献边界、实验协议和论文叙事一致。
在 Edit、Write、Review、Figure 模式中，先用项目记忆、当前文件和用户显式附加文件判断改动是否支持研究目标；如果可能改变核心 claim、数据划分、指标口径、实验结论、章节语义或图表证据，必须先指出“漂移风险”，并询问用户确认，不要直接生成 Write/Edit 提案。
生成待审批变更时，说明变更目标、影响的研究产物、和研究目标的关系。不要把工具过程、草稿 diff 或审批内容写进思考过程；正式回答只总结可执行结论、风险和待用户审批的变更。
多轮对话中，用户显式附加的文件优先级高于自动检索文件；当前活动文件只代表默认工作对象，不应覆盖用户明确指定的章节、文件或 artifact。
"""

CHAT_CONTEXT_ASK_SYSTEM_PROMPT = """你是科研代码和论文解释助手。
只基于用户提供的上下文回答，不调用工具，不修改文件，不扫描项目目录。
用中文结构化回答，优先解释输入、输出、流程、关键逻辑和明显风险。
回答控制在 8-10 条要点内；如果上下文显示语法错误或配置风险，直接指出。"""

CHAT_CONFIG_CHANGE_PROMPT = """

## 配置变更任务规则

用户正在要求调整实验/训练配置。请按这个顺序处理：
1. 先在 experiments/ 内定位配置文件，优先检查 experiments/configs、experiments/**/*.yaml、experiments/**/*.yml、experiments/**/*.json、experiments/**/*.toml。
2. 如果用户说“预训练”，搜索文件名或内容中的 pretrain、pretraining、pre_train、pre-training、train_stage、stage、task，并优先修改预训练配置。
3. 对 batch_size、learning_rate/lr、epochs、num_workers、optimizer 等参数，优先修改显式配置文件中的 training.* 字段。
4. 不要把 data.py、train.py 中的 deep_get(..., 默认值) 当成首选目标；那只是 fallback，通常不会改变实际实验。
5. 只有一个明显候选时，直接生成待审批 Edit 提案；多个候选时，先列出候选并询问用户确认。
"""


def _looks_like_config_change(message: str) -> bool:
    text = (message or "").lower()
    markers = (
        "batch_size", "batch size", "learning_rate", "learning rate", " lr", "lr=",
        "epoch", "num_workers", "num workers", "optimizer", "pretrain", "pre-training",
        "config", "yaml", "yml", "toml", "json",
    )
    chinese_markers = ("调高", "调低", "提高", "降低", "增大", "减小", "预训练", "配置", "学习率", "批大小")
    return any(marker in text for marker in markers) or any(marker in (message or "") for marker in chinese_markers)


def _chat_task_hint(raw_user_msg: str, mode: str) -> str:
    if mode == "edit" and _looks_like_config_change(raw_user_msg):
        return CHAT_CONFIG_CHANGE_PROMPT
    return ""

def _looks_like_project_overview_request(message: str) -> bool:
    text = (message or "").lower()
    chinese = ("研究项目", "当前项目", "项目目标", "项目结构", "关键逻辑", "下一步建议", "整体目标", "项目概览")
    english = ("project goal", "project structure", "project overview", "next step", "key logic", "research project")
    return any(marker in (message or "") for marker in chinese) or any(marker in text for marker in english)


def _artifact_priority(path) -> tuple[int, str]:
    normalized = str(path).replace("\\", "/").lower()
    priority_names = (
        "ideas/", "paper/main.tex", "paper/", "experiments/config", "experiments/src/train.py", "NARRATIVE_REPORT.md",
        "experiments/src/data.py", "experiments/src/model.py", "experiments/src/metrics.py", "slides/", "figures/",
    )
    for index, marker in enumerate(priority_names):
        if marker in normalized:
            return index, normalized
    return 99, normalized


def _build_project_overview_context(project_path: str) -> str:
    """Build a bounded project overview context without asking the model to call tools first."""
    from pathlib import Path

    root = Path(project_path or ".").expanduser().resolve()
    blocks = []
    inventory = []
    candidates = []
    text_exts = {".tex", ".md", ".markdown", ".rst", ".py", ".yaml", ".yml", ".json", ".toml", ".csv"}

    for dirname in RESEARCH_ARTIFACT_DIRS:
        artifact_dir = (root / dirname).resolve()
        if not artifact_dir.exists() or not artifact_dir.is_dir():
            continue
        files = [p for p in artifact_dir.rglob("*") if p.is_file()]
        inventory.append(f"- {dirname}/: {len(files)} files")
        for file_path in files:
            if file_path.suffix.lower() not in text_exts:
                continue
            rel = file_path.relative_to(root)
            normalized = str(rel).replace("\\", "/").lower()
            if any(part in normalized for part in ("/__pycache__/", "/checkpoints/", "/logs/", "/results/")):
                continue
            candidates.append(file_path)

    candidates = sorted(candidates, key=_artifact_priority)[:10]
    for file_path in candidates:
        try:
            content = file_path.read_text(encoding="utf-8", errors="replace")
            rel = file_path.relative_to(root)
            blocks.append(
                f"### {rel}\n```\n{_compact_context_content(file_path, content)}\n```"
            )
        except Exception as e:
            blocks.append(f"### {file_path}\n[读取失败: {e}]")

    if not inventory and not blocks:
        return "\n\n## 项目概览上下文\n未在 paper/、slides/、experiments/、figures/、literature/、ideas/ 中发现可读取的研究产物。"

    return (
        "\n\n## 项目概览上下文\n"
        "以下上下文由后端从研究产物目录自动打包，用于回答项目目标、结构、关键逻辑和下一步建议；不包含 IDE 自身源码。\n\n"
        "### 产物目录清单\n"
        + ("\n".join(inventory) if inventory else "未发现研究产物目录。")
        + "\n\n"
        + "\n\n".join(blocks)
    )



def _normalize_chat_mode(mode: str) -> str:
    mode = (mode or "ask").strip().lower()
    return mode if mode in CHAT_MODE_TOOLS else "edit"


def _chat_role_for_mode(mode: str) -> ModelRole:
    return CHAT_MODE_ROLES.get(_normalize_chat_mode(mode), ModelRole.EXECUTOR)


def _chat_tools_for_mode(mode: str) -> list[str]:
    return CHAT_MODE_TOOLS.get(_normalize_chat_mode(mode), CHAT_MODE_TOOLS["ask"])


def _chat_system_prompt(user_input: str) -> str:
    if (user_input or "").strip().startswith('/'):
        return get_system_prompt_for_command(user_input)
    return COPILOT_SYSTEM_PROMPT


def _compact_python_context(path, content: str, max_chars: int = 3200) -> str:
    """Compress long Python files before sending them to chat models.

    Some OpenAI-compatible pools respond reliably to short prompts but hang on
    ~10k character source dumps. Keep enough structure for explanation tasks
    while staying below the slow-path threshold.
    """
    if len(content) <= max_chars:
        return content

    import re

    lines = content.splitlines()
    signatures = []
    for index, line in enumerate(lines, start=1):
        stripped = line.strip()
        if re.match(r"^(async\s+def|def|class)\s+", stripped):
            signatures.append(f"L{index}: {stripped[:140]}")

    def take_prefix(src: str, max_len: int) -> str:
        picked = []
        total = 0
        for line in src.splitlines():
            next_total = total + len(line) + 1
            if next_total > max_len:
                break
            picked.append(line)
            total = next_total
        return "\n".join(picked).rstrip()

    def take_suffix(src: str, max_len: int) -> str:
        picked = []
        total = 0
        for line in reversed(src.splitlines()):
            next_total = total + len(line) + 1
            if next_total > max_len:
                break
            picked.append(line)
            total = next_total
        return "\n".join(reversed(picked)).lstrip()

    head_chars = 1750
    tail_chars = 750
    head = take_prefix(content, head_chars)
    tail = take_suffix(content, tail_chars)
    definition_index = "\n".join(signatures[:40]) or "未识别到顶层 def/class。"
    compact = (
        f"# 文件较长，已压缩为结构化上下文以避免模型请求超时。\n"
        f"# 原始长度: {len(content)} 字符；路径: {path}\n\n"
        f"# 顶层定义索引\n{definition_index}\n\n"
        f"# 文件开头摘录\n{head}\n\n"
        f"# 文件结尾摘录\n{tail}"
    )
    if len(compact) > max_chars:
        compact = compact[:max_chars] + "\n\n# [上下文已截断，保留了文件开头、结尾和定义索引]"
    return compact


def _take_prefix(src: str, max_len: int) -> str:
    picked = []
    total = 0
    for line in src.splitlines():
        next_total = total + len(line) + 1
        if next_total > max_len:
            break
        picked.append(line)
        total = next_total
    return "\n".join(picked).rstrip()


def _take_suffix(src: str, max_len: int) -> str:
    picked = []
    total = 0
    for line in reversed(src.splitlines()):
        next_total = total + len(line) + 1
        if next_total > max_len:
            break
        picked.append(line)
        total = next_total
    return "\n".join(reversed(picked)).lstrip()


def _compact_latex_context(path, content: str, max_chars: int = 4600) -> str:
    if len(content) <= max_chars:
        return content

    import re

    headings = []
    for index, line in enumerate(content.splitlines(), start=1):
        stripped = line.strip()
        match = re.match(r"\\(part|chapter|section|subsection|subsubsection)\*?\{(.{1,180})\}", stripped)
        if match:
            headings.append(f"L{index}: \\{match.group(1)}{{{match.group(2)}}}")

    heading_index = "\n".join(headings[:60]) or "未识别到 LaTeX section/subsection 标题。"
    compact = (
        f"% 文件较长，已按 LaTeX 结构压缩以保留论文脉络。\n"
        f"% 原始长度: {len(content)} 字符；路径: {path}\n\n"
        f"% 章节索引\n{heading_index}\n\n"
        f"% 文件开头摘录\n{_take_prefix(content, 2200)}\n\n"
        f"% 文件结尾摘录\n{_take_suffix(content, 1000)}"
    )
    if len(compact) > max_chars:
        compact = compact[:max_chars] + "\n\n% [上下文已截断，保留了章节索引、开头和结尾]"
    return compact


def _compact_markdown_context(path, content: str, max_chars: int = 4200) -> str:
    if len(content) <= max_chars:
        return content

    headings = []
    for index, line in enumerate(content.splitlines(), start=1):
        stripped = line.strip()
        if stripped.startswith("#"):
            headings.append(f"L{index}: {stripped[:180]}")

    compact = (
        f"<!-- 文件较长，已按 Markdown 结构压缩。路径: {path}; 原始长度: {len(content)} 字符 -->\n\n"
        f"## 标题索引\n{chr(10).join(headings[:60]) or '未识别到 Markdown 标题。'}\n\n"
        f"## 文件开头摘录\n{_take_prefix(content, 2100)}\n\n"
        f"## 文件结尾摘录\n{_take_suffix(content, 900)}"
    )
    if len(compact) > max_chars:
        compact = compact[:max_chars] + "\n\n[上下文已截断，保留了标题索引、开头和结尾]"
    return compact


def _compact_context_content(path, content: str) -> str:
    if len(content) <= 3200:
        return content
    suffix = getattr(path, "suffix", "").lower()
    if suffix in {".py", ".pyw"}:
        return _compact_python_context(path, content)
    if suffix in {".tex", ".ltx"}:
        return _compact_latex_context(path, content)
    if suffix in {".md", ".markdown", ".rst"}:
        return _compact_markdown_context(path, content)
    if suffix in {".yaml", ".yml", ".json", ".toml"}:
        return _take_prefix(content, 5200) + "\n\n[上下文已截断：配置文件较长，仅发送前部关键配置。]"
    return _take_prefix(content, 3600) + "\n\n" + _take_suffix(content, 900) + "\n\n[上下文已截断：保留文件开头和结尾以避免模型请求超时。]"


def _compact_chat_text(text: str, max_chars: int = 1200) -> str:
    text = (text or "").strip()
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + "\n[该轮内容已压缩截断]"


def _build_conversation_context_block(messages) -> str:
    if not isinstance(messages, list):
        return ""

    cleaned = []
    for item in messages[-24:]:
        if not isinstance(item, dict):
            continue
        role = item.get("role") if item.get("role") in {"user", "assistant"} else "assistant"
        content = _compact_chat_text(str(item.get("content", "")), 1600)
        proposals = item.get("changeProposals") if isinstance(item.get("changeProposals"), list) else []
        proposal_summary = []
        for proposal in proposals[:8]:
            if isinstance(proposal, dict):
                proposal_summary.append(
                    f"{proposal.get('action', 'change')} {proposal.get('path', '')} [{proposal.get('status', '?')}]"
                )
        if content or proposal_summary:
            cleaned.append({"role": role, "content": content, "proposals": proposal_summary})

    if not cleaned:
        return ""

    older = cleaned[:-10]
    recent = cleaned[-10:]
    lines = [
        "\n\n## 多轮会话上下文",
        "以下是同一 Chat 会话的压缩历史，用于在后端 session 丢失、切换模式或切换当前文件后保持任务连续性。不要把历史中未获批准的变更当成已生效事实。",
    ]
    if older:
        lines.append("\n### 更早轮次摘要")
        for item in older[-8:]:
            first_line = item["content"].splitlines()[0] if item["content"] else ""
            if first_line:
                lines.append(f"- {item['role']}: {first_line[:220]}")
            for proposal in item["proposals"]:
                lines.append(f"  - proposal: {proposal[:220]}")

    lines.append("\n### 最近轮次")
    for item in recent:
        lines.append(f"\n[{item['role']}]\n{item['content'] or '[无正文]'}")
        if item["proposals"]:
            lines.append("变更提案状态：" + "; ".join(item["proposals"]))
    return "\n".join(lines)


def _build_context_block(project_path: str, context_files) -> str:
    if not isinstance(context_files, list):
        return ""

    blocks = []
    seen = set()
    for item in context_files[:8]:
        source = "explicit"
        if isinstance(item, dict):
            raw_path = str(item.get("path", ""))
            source = str(item.get("source", "explicit") or "explicit")
        else:
            raw_path = str(item or "")
        if not raw_path or raw_path in seen:
            continue
        seen.add(raw_path)
        p = _resolve_chat_artifact_path(project_path, raw_path)
        if not p:
            continue
        try:
            content = p.read_text(encoding="utf-8", errors="replace")
            compact_content = _compact_context_content(p, content)
            blocks.append(f"### {p.name}\n路径: {p}\n来源: {source}\n```\n{compact_content}\n```")
        except Exception as e:
            blocks.append(f"### {raw_path}\n[读取失败: {e}]")

    if not blocks:
        return ""
    return "\n\n## 上下文文件\n以下文件是用户当前打开或显式附加的研究产物。显式附加文件代表用户本轮意图，应优先于自动检索；不要为了理解当前文件而枚举项目根目录。\n" + "\n\n".join(blocks)


def _apply_chat_scope(session, project_path: str):
    session.tool_policy = "research_artifacts"
    session.project_path = project_path or "."
    if session.messages and session.messages[0].role == "system":
        content = session.messages[0].content
        if "## Chat 面板范围" not in content:
            content += CHAT_SCOPE_PROMPT
        if "## 科研目标对齐" not in content:
            content += CHAT_ALIGNMENT_PROMPT
        session.messages[0].content = content


def _is_chat_artifact_path(project_path: str, path: str) -> bool:
    from pathlib import Path
    if not path:
        return False
    root = Path(project_path or ".").expanduser().resolve()
    target = Path(path).expanduser()
    if not target.is_absolute():
        target = root / target
    target = target.resolve()
    for filename in RESEARCH_ARTIFACT_FILES:
        if target == (root / filename).resolve():
            return True
    for dirname in RESEARCH_ARTIFACT_DIRS:
        allowed_root = (root / dirname).resolve()
        try:
            target.relative_to(allowed_root)
            return True
        except ValueError:
            if target == allowed_root:
                return True
    return False

def _resolve_chat_artifact_path(project_path: str, path: str):
    from pathlib import Path
    if not _is_chat_artifact_path(project_path, path):
        return None
    root = Path(project_path or ".").expanduser().resolve()
    target = Path(path).expanduser()
    if not target.is_absolute():
        target = root / target
    return target.resolve()

def _chat_history_path(project_path: str):
    from pathlib import Path
    root = Path(project_path or ".").expanduser().resolve()
    return root / ".merak" / "chat" / CHAT_HISTORY_FILE


def _clean_str(value: Any, max_len: int = 1000) -> str:
    if value is None:
        return ""
    text = str(value)
    return text[:max_len]


def _sanitize_chat_message(message: Any) -> dict:
    if not isinstance(message, dict):
        return {}
    role = message.get("role") if message.get("role") in {"user", "assistant"} else "assistant"
    clean = {
        "id": _clean_str(message.get("id"), 128) or f"msg_{int(time.time() * 1000)}",
        "role": role,
        "content": _clean_str(message.get("content"), MAX_CHAT_MESSAGE_CHARS),
        "timestamp": message.get("timestamp") if isinstance(message.get("timestamp"), (int, float)) else int(time.time() * 1000),
    }
    if isinstance(message.get("toolCalls"), list):
        clean["toolCalls"] = message["toolCalls"][:50]
    if isinstance(message.get("toolResults"), list):
        clean["toolResults"] = message["toolResults"][:50]
    if isinstance(message.get("steps"), list):
        clean["steps"] = message["steps"][:100]
    if isinstance(message.get("changeProposals"), list):
        clean["changeProposals"] = message["changeProposals"][:50]
    if isinstance(message.get("imageUrl"), str):
        clean["imageUrl"] = _clean_str(message.get("imageUrl"), 4096)
    return clean


def _sanitize_chat_history(payload: dict) -> dict:
    raw_conversations = payload.get("conversations") if isinstance(payload, dict) else []
    conversations = []
    if isinstance(raw_conversations, list):
        for item in raw_conversations[:MAX_CHAT_HISTORY_CONVERSATIONS]:
            if not isinstance(item, dict):
                continue
            messages = item.get("messages") if isinstance(item.get("messages"), list) else []
            attached = item.get("attachedFiles") if isinstance(item.get("attachedFiles"), list) else []
            clean_attached = []
            for f in attached[:24]:
                if isinstance(f, dict):
                    source = f.get("source") if f.get("source") in {"explicit", "current"} else "explicit"
                    clean_attached.append({
                        "path": _clean_str(f.get("path"), 4096),
                        "name": _clean_str(f.get("name"), 512),
                        "source": source,
                    })
            conv_id = _clean_str(item.get("id"), 128) or f"chat_{int(time.time() * 1000)}"
            conversations.append({
                "id": conv_id,
                "backendSessionId": _clean_str(item.get("backendSessionId"), 128),
                "backendContextKey": _clean_str(item.get("backendContextKey"), 4096),
                "title": _clean_str(item.get("title"), 128) or "新会话",
                "messages": [m for m in (_sanitize_chat_message(msg) for msg in messages[-MAX_CHAT_HISTORY_MESSAGES:]) if m],
                "attachedFiles": clean_attached,
                "mode": item.get("mode") if item.get("mode") in CHAT_MODE_TOOLS else "ask",
                "provider": _clean_str(item.get("provider"), 128),
                "projectPath": _clean_str(item.get("projectPath"), 4096),
                "createdAt": item.get("createdAt") if isinstance(item.get("createdAt"), (int, float)) else int(time.time() * 1000),
                "updatedAt": item.get("updatedAt") if isinstance(item.get("updatedAt"), (int, float)) else int(time.time() * 1000),
            })
    active_id = _clean_str(payload.get("activeConversationId") if isinstance(payload, dict) else "", 128)
    if conversations and not any(c["id"] == active_id for c in conversations):
        active_id = conversations[0]["id"]
    return {"activeConversationId": active_id, "conversations": conversations}

def _ensure_init():
    global _initialized
    if not _initialized:
        # 启动时先从持久化配置写入环境变量，再初始化 model_router
        try:
            from ..api.settings import load_settings
            from ..api.settings import apply_model_config
            saved = load_settings()
            apply_model_config(saved.models)
        except Exception:
            init_models_from_env()
        register_all_tools()
        _initialized = True
