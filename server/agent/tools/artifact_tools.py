"""Focused artifact tools for the MERAK agent surface."""

from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path

import structlog

from ...utils.atomic_write import atomic_write_json, atomic_write_text


logger = structlog.get_logger()
FILE_READ_MAX_CHARS = 128_000


async def figure_manifest(project_path: str) -> str:
    """Return the persistent figure manifest used by paper-writing and preview UI."""
    from server.services.figure_artifacts import figure_artifact_registry

    figures_dir = Path(project_path).expanduser().resolve() / "figures"
    payload = figure_artifact_registry.load(figures_dir)
    return json.dumps(payload, ensure_ascii=False, indent=2)


# ==================== Paper Scaffolding ====================

async def scaffold_paper_tool(
    project_dir: str, venue: str, title: str = "Paper Title",
    author: str = "Author", affiliation: str = "University"
) -> str:
    """从模板创建论文项目"""
    from server.services.paper_compiler import scaffold_paper
    result = await scaffold_paper(project_dir, venue, title, author, affiliation)
    if result["success"]:
        return f"{result['message']}\nFiles created: {', '.join(result['files_created'])}"
    else:
        raise RuntimeError(f"Scaffold failed: {result['message']}")


# ==================== Overleaf Sync ====================

async def overleaf_sync_tool(action: str, project_id: str) -> str:
    """Overleaf 同步操作"""
    from server.services.overleaf_sync import overleaf_sync
    if action == "pull":
        result = await overleaf_sync.pull(project_id)
    elif action == "push":
        result = await overleaf_sync.push(project_id)
    elif action == "sync":
        result = await overleaf_sync.sync(project_id)
    else:
        return f"Unknown action: {action}. Use pull/push/sync."

    if result.success:
        return f"{result.message}\nFiles changed: {', '.join(result.files_changed[:10])}"
    else:
        raise RuntimeError(f"Sync failed: {result.message}")


# ==================== Security & Integrity Tools ====================

async def threat_scan(content: str, scope: str = "context") -> str:
    """扫描内容中的 prompt injection / 恶意代码

    scope: all | context | strict
    - all: 基础注入+外泄检测
    - context: + promptware/C2/角色劫持
    - strict: + 持久化/后门/密钥泄漏
    """

    # 基础注入模式
    patterns_all = [
        (r'ignore\s+(all\s+)?previous\s+instructions', 'prompt_injection'),
        (r'you\s+are\s+now\s+(a|an)\s+', 'role_hijack'),
        (r'system\s*:\s*', 'system_override'),
        (r'<\|im_start\|>', 'format_injection'),
        (r'ANTHROPIC_API_KEY|OPENAI_API_KEY|sk-[a-zA-Z0-9]{20,}', 'secret_leak'),
        (r'curl\s+.*\|\s*(bash|sh)', 'remote_exec'),
        (r'eval\s*\(', 'code_injection'),
    ]

    # Context 级别追加
    patterns_context = [
        (r'act\s+as\s+(if\s+)?you\s+', 'persona_override'),
        (r'forget\s+(everything|all)', 'memory_wipe'),
        (r'do\s+not\s+follow\s+', 'instruction_override'),
        (r'base64\s*decode|atob\(', 'obfuscation'),
    ]

    # Strict 级别追加
    patterns_strict = [
        (r'ssh\s+.*@', 'ssh_backdoor'),
        (r'chmod\s+\+s|setuid', 'privilege_escalation'),
        (r'crontab|systemctl\s+enable', 'persistence'),
        (r'https?://[^\s]+\.(tk|ml|ga|cf|gq)/', 'suspicious_url'),
    ]

    # 选择检测级别
    active_patterns = patterns_all[:]
    if scope in ('context', 'strict'):
        active_patterns.extend(patterns_context)
    if scope == 'strict':
        active_patterns.extend(patterns_strict)

    findings = []
    for pattern, category in active_patterns:
        matches = re.findall(pattern, content, re.IGNORECASE)
        if matches:
            findings.append(f"[{category}] {len(matches)} match(es): pattern={pattern}")

    if findings:
        return f"⚠️ THREAT DETECTED ({len(findings)} issues):\n" + "\n".join(findings)
    return f"✅ CLEAN (scope={scope}, {len(content)} chars scanned)"


async def evidence_check(claim: str, source_path: str, cited_value: str = "") -> str:
    """验证声明的证据是否存在

    机械验证：cited 的文件是否存在，cited 的数值是否出现在文件中。
    不判断正确性（那是 reviewer 的工作），只判断存在性。
    """
    p = Path(source_path)
    if not p.exists():
        return f"❌ HALLUCINATION: Source file does not exist: {source_path}"

    content = p.read_text(encoding='utf-8', errors='replace')

    if cited_value:
        # 查找引用的数值
        if cited_value in content:
            return f"✅ VERIFIED: Value '{cited_value}' found in {source_path}"
        # 尝试数值匹配（去掉格式差异）
        import re
        normalized = cited_value.replace('%', '').replace(',', '').strip()
        if re.search(r'\b' + re.escape(normalized) + r'\b', content):
            return f"✅ VERIFIED: Value '{cited_value}' found (normalized) in {source_path}"
        return f"⚠️ UNVERIFIED: Value '{cited_value}' NOT found in {source_path}. File exists but value missing. Send to reviewer jury."

    return f"✅ SOURCE EXISTS: {source_path} ({len(content)} chars)"


async def provenance_stamp(artifact_path: str, author_model: str, reviewer_model: str = "", verdict: str = "") -> str:
    """记录文件的来源信息（谁生成、谁审核）

    Reviewer 可以与 author 使用同一模型；会话隔离由审稿传输层保证。
    """

    p = Path(artifact_path)
    if not p.exists():
        raise FileNotFoundError(f"Artifact not found: {artifact_path}")

    content = p.read_text(encoding='utf-8', errors='replace')
    content_hash = hashlib.sha256(content.encode()).hexdigest()[:16]

    # 写入 provenance 记录
    prov_dir = p.parent / ".merak" / "provenance"
    prov_dir.mkdir(parents=True, exist_ok=True)

    record = {
        "artifact": str(p),
        "content_hash": content_hash,
        "author_model": author_model,
        "reviewer_model": reviewer_model or None,
        "same_model_allowed": True,
        "same_model": bool(
            reviewer_model
            and reviewer_model.casefold() == author_model.casefold()
        ),
        "session_isolation": "enforced_by_review_transport",
        "verdict": verdict or None,
        "timestamp": time.time(),
    }

    prov_file = prov_dir / f"{p.name}.provenance.json"
    atomic_write_json(prov_file, record)

    return f"✅ Provenance recorded: {p.name} by {author_model}" + (f", reviewed by {reviewer_model}" if reviewer_model else "")


async def extract_paper_style(source_path: str) -> str:
    """从参考论文提取写作风格 profile（结构骨架，不复制内容）"""
    p = Path(source_path)
    if not p.exists():
        raise FileNotFoundError(f"File not found: {source_path}")

    content = p.read_text(encoding='utf-8', errors='replace')

    # 提取结构信息
    sections = re.findall(r'\\section\{([^}]+)\}', content)
    subsections = re.findall(r'\\subsection\{([^}]+)\}', content)
    figures = re.findall(r'\\begin\{figure', content)
    tables = re.findall(r'\\begin\{table', content)
    theorems = re.findall(r'\\begin\{theorem', content)
    equations = re.findall(r'\\begin\{equation', content)
    citations = re.findall(r'\\cite\{', content)

    # 计算段落长度分布
    paragraphs = [p.strip() for p in content.split('\n\n') if len(p.strip()) > 50]
    avg_para_len = sum(len(p) for p in paragraphs) / max(len(paragraphs), 1)

    profile = f"""## Style Profile: {p.name}

### Structure
- Sections: {', '.join(sections) if sections else 'N/A'}
- Subsections: {len(subsections)}
- Figures: {len(figures)}
- Tables: {len(tables)}
- Theorems: {len(theorems)}
- Equations: {len(equations)}
- Citations: {len(citations)}

### Writing Style
- Average paragraph length: {int(avg_para_len)} chars
- Total paragraphs: {len(paragraphs)}
- Section ordering: {' → '.join(sections[:8]) if sections else 'N/A'}

### Constraints
- DO NOT copy prose, claims, or terminology from this paper
- ONLY mimic structural patterns (section ordering, density ratios, formatting)
"""

    # 缓存 style profile
    cache_dir = p.parent / ".merak" / "style_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_text(cache_dir / f"{p.stem}_style.md", profile)

    return profile


async def watchdog_check(server_id: str, session_prefix: str = "merak_exp_") -> str:
    """检查远程实验进程是否还活着

    查询所有以 session_prefix 开头的 screen session 状态。
    返回每个 session 的状态：ALIVE / DEAD / STALLED
    """
    from server.services.ssh_manager import ssh_manager

    # 列出所有相关 screen session
    stdout, stderr, exit_code = await ssh_manager.execute(
        server_id,
        f"screen -ls | grep '{session_prefix}' || echo 'NO_SESSIONS'",
        timeout=10,
    )

    if "NO_SESSIONS" in stdout or not stdout.strip():
        return "No active experiment sessions found."

    lines = stdout.strip().splitlines()
    results = []
    for line in lines:
        parts = line.strip().split('\t')
        if len(parts) >= 2:
            session_name = parts[0].strip()
            status = "ALIVE" if "Attached" in line or "Detached" in line else "DEAD"
            results.append(f"  {session_name}: {status}")

    # 检查 GPU 利用率（判断是否 stalled）
    try:
        gpu_stdout, _, _ = await ssh_manager.execute(
            server_id,
            "nvidia-smi --query-gpu=utilization.gpu --format=csv,noheader,nounits 2>/dev/null || echo '-1'",
            timeout=5,
        )
        gpu_utils = [int(x.strip()) for x in gpu_stdout.strip().splitlines() if x.strip().isdigit()]
        if gpu_utils and all(u < 5 for u in gpu_utils):
            results.append("  WARNING: All GPUs idle (<5% utilization); experiments may be stalled")
    except Exception as exc:
        logger.debug("Remote GPU utilization probe failed", server_id=server_id, error=str(exc))

    return f"Experiment sessions on {server_id}:\n" + "\n".join(results)


# ==================== 注册所有工具 ====================

