"""Focused review and domain tools for the MERAK agent surface."""

from __future__ import annotations

import asyncio
import json
import os
import re
import time
from pathlib import Path
from typing import Any, Optional

import structlog

from ...utils.atomic_write import atomic_write_json, atomic_write_text, path_lock
from .literature_tools import web_search


logger = structlog.get_logger()
FILE_READ_MAX_CHARS = 128_000


async def cross_model_review(
    content: str = "",
    reviewer_prompt: str = "",
    file_path: str = "",
    prompt: str = "",
    config: Optional[dict[str, Any]] = None,
    model: str = "",
    project_path: str = "",
) -> str:
    """Execute the native reviewer_api tool in a fresh read-only review session.

    用 REVIEWER 模型（OpenAI/GPT）对内容进行批判性审稿。
    遵循 Reviewer Independence 原则：
    - 优先传 file_path 让 reviewer 自己读取文件（零信息泄漏）
    - 如果传 content，reviewer 也只看到原始内容（不加 executor 解释）
    - 每次调用保存 trace 到 .merak/traces/
    """
    from ..engine import agent_engine
    from .. import ModelRole
    from ..reviewer_scope import review_root, bind_review_scope
    root = review_root(project_path, file_path)

    request_parts = [part.strip() for part in (prompt, content) if str(part or "").strip()]
    artifact_content = ""
    if file_path:
        try:
            artifact = Path(file_path).expanduser()
            artifact = (root / artifact if root and not artifact.is_absolute() else artifact).resolve()
            if root and not artifact.is_relative_to(root):
                raise ValueError("Reviewer artifact escapes its project")
            artifact_content = artifact.read_text(
                encoding="utf-8",
                errors="replace",
            )
        except Exception as e:
            raise RuntimeError(f"Unable to read review artifact {file_path}: {e}") from e
        request_parts.append(f"--- Artifact: {file_path} ---\n{artifact_content}")
    if not request_parts:
        raise ValueError(
            "TOOL_SCHEMA_ERROR: `reviewer_api` requires one of "
            "`prompt`, `content`, or `file_path`."
        )
    actual_content = "\n\n".join(request_parts)

    system_prompt = reviewer_prompt or """You are a critical scientific reviewer at a top ML venue (ICLR/NeurIPS).
Review the following content rigorously. Identify:
1. Technical flaws or unsupported claims
2. Missing baselines or comparisons
3. Clarity and presentation issues
4. Novelty concerns

Output: Overall Score (1-10), Strengths, Weaknesses, Questions, Suggestions.

IMPORTANT: You are reading the artifact COLD. The executor has no chance to explain or contextualize. Judge only what is on the page."""

    session = agent_engine.create_session(
        system_prompt=system_prompt,
        role=ModelRole.REVIEWER,
    )
    tools = bind_review_scope(session, root, new_session=True)
    result = await agent_engine.run(session_id=session.id, user_message=actual_content, tools=tools)

    # Review Tracing — 保存到 .merak/traces/
    try:
        _save_review_trace(
            "cross_model_review",
            actual_content,
            result,
            file_path,
            project_path=project_path,
        )
    except Exception as exc:
        raise RuntimeError(
            "Independent review completed but its provenance trace could not be saved"
        ) from exc

    return f"[thread:{session.id}]\n{result}"


def _save_review_trace(
    skill_name: str,
    input_text: str,
    output_text: str,
    file_path: str = "",
    *,
    project_path: str = "",
):
    """保存审稿 trace 到 .merak/traces/<skill>/<date>_run<NN>/"""
    from datetime import datetime

    root = Path(project_path).expanduser().resolve() if project_path else None
    if root is None and file_path:
        artifact = Path(file_path).expanduser().resolve()
        start = artifact if artifact.is_dir() else artifact.parent
        root = next(
            (candidate for candidate in (start, *start.parents) if (candidate / ".merak").is_dir()),
            None,
        )
    root = root or Path.cwd().resolve()
    trace_base = root / ".merak" / "traces" / skill_name
    trace_base.mkdir(parents=True, exist_ok=True)

    # 生成目录名：日期_运行编号
    date_str = datetime.now().strftime("%Y%m%d")
    existing = list(trace_base.glob(f"{date_str}_run*"))
    run_num = len(existing) + 1
    trace_dir = trace_base / f"{date_str}_run{run_num:02d}"
    trace_dir.mkdir(parents=True, exist_ok=True)

    # 保存 trace 文件
    trace_data = {
        "timestamp": time.time(),
        "skill": skill_name,
        "file_path": file_path,
        "input_length": len(input_text),
        "output_length": len(output_text),
    }
    atomic_write_json(trace_dir / "meta.json", trace_data)
    atomic_write_text(trace_dir / "input.txt", input_text)
    atomic_write_text(trace_dir / "output.txt", output_text)


async def ask_user_question(question: str, options: str = "") -> str:
    """向用户提问并等待回答（替代 AskUserQuestion）

    通过 WebSocket 推送问题给前端，等待用户回答。
    如果有 WebSocket 连接，推送并等待；否则 auto-proceed。
    """
    from ..ws.router import push_question_and_wait

    try:
        # 尝试通过 WebSocket 推送问题到前端
        answer = await push_question_and_wait(question, options)
        if answer:
            return answer
    except Exception as exc:
        logger.warning("Interactive question delivery failed; using auto policy", error=str(exc))

    # Fallback: auto-proceed
    if options:
        first_option = options.split(',')[0].strip()
        return f"[Auto-proceed] Selected: {first_option}"
    return "[Auto-proceed] User confirmed."


async def cross_model_review_reply(
    thread_id: str,
    message: str,
    project_path: str = "",
) -> str:
    """跨模型审稿多轮对话（替代 reviewer_api_reply）

    在已有的审稿线程中继续对话（如回复修改后要求重新审稿）。
    """
    from ..engine import agent_engine
    from .. import ModelRole
    from ..reviewer_scope import review_root, bind_review_scope
    root = review_root(project_path)

    # 查找已有 session 或创建新的
    session = agent_engine._sessions.get(thread_id)
    if session is None and root:
        session = agent_engine.restore_session(thread_id, str(root))
    new_session = session is None
    if not session:
        # 没有现有线程，创建新的 reviewer session
        session = agent_engine.create_session(
            system_prompt="You are a critical reviewer continuing a multi-round review. The author has revised based on your previous feedback. Re-evaluate.",
            role=ModelRole.REVIEWER,
        )
        thread_id = session.id

    tools = bind_review_scope(session, root, new_session=new_session)
    result = await agent_engine.run(session_id=session.id, user_message=message, tools=tools)
    try:
        _save_review_trace(
            "cross_model_review_reply",
            message,
            result,
            project_path=project_path,
        )
    except Exception as exc:
        raise RuntimeError(
            "Independent review reply completed but its provenance trace could not be saved"
        ) from exc
    return f"[thread:{session.id}]\n{result}"


async def gemini_search(query: str, max_results: int = 10) -> str:
    """Gemini 搜索增强（替代 mcp__gemini-cli__*）

    优先用 Gemini API（如果配置了），否则降级到 WebSearch。
    """
    gemini_key = os.environ.get("GEMINI_API_KEY", "")
    if gemini_key:
        try:
            import httpx
            # Gemini grounding with Google Search
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={gemini_key}"
            payload = {
                "contents": [{"parts": [{"text": f"Search and summarize: {query}"}]}],
                "tools": [{"google_search": {}}],
            }
            async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
                resp = await client.post(url, json=payload)
                if resp.status_code == 200:
                    data = resp.json()
                    candidates = data.get("candidates", [])
                    if candidates:
                        parts = candidates[0].get("content", {}).get("parts", [])
                        text = "\n".join(p.get("text", "") for p in parts if p.get("text"))
                        return text[:3000] if text else "No results from Gemini"
                    return "No results from Gemini"
                else:
                    # Gemini 失败，降级到 WebSearch
                    return await web_search(query, max_results)
        except Exception as exc:
            logger.warning("Gemini search failed; falling back to web search", error=str(exc))
            return await web_search(query, max_results)
    else:
        # 没有 Gemini key，降级到 WebSearch
        return await web_search(query, max_results)


async def zotero_search(query: str, limit: int = 10) -> str:
    """Zotero 文献库搜索（替代 mcp__zotero__*）

    从用户的 Zotero 库中搜索文献。需要 ZOTERO_API_KEY 和 ZOTERO_USER_ID。
    """
    try:
        from server.services.knowledge_sources import knowledge_source_service

        items = await knowledge_source_service.search_zotero(query, limit)
        return json.dumps({"source": "zotero", "query": query, "records": items}, ensure_ascii=False, indent=2)
    except Exception as e:
        raise RuntimeError(f"Zotero search failed: {e}") from e


async def obsidian_read(vault_path: str = "", query: str = "") -> str:
    """Obsidian 笔记读取（替代 mcp__obsidian-vault__*）

    搜索或读取用户 Obsidian vault 中的笔记。
    """
    try:
        from server.services.knowledge_sources import knowledge_source_service

        items = knowledge_source_service.search_obsidian(query, vault_path=vault_path, limit=15)
        return json.dumps({"source": "obsidian", "query": query, "records": items}, ensure_ascii=False, indent=2)
    except Exception as e:
        raise RuntimeError(f"Obsidian read failed: {e}") from e


# ==================== LaTeX ====================

async def latex_compile(project_dir: str, main_tex: str = "main.tex") -> str:
    """编译 LaTeX 论文"""
    from server.services.paper_compiler import paper_compiler
    result = await paper_compiler.compile(project_dir, main_tex)
    if result.success:
        return f"✅ Compiled successfully: {result.pages} pages, {result.compile_time_ms}ms"
    else:
        errors = '\n'.join(f"  L{e.line}: {e.message}" for e in result.errors[:5])
        raise RuntimeError(f"Compilation failed:\n{errors}")


# ==================== GPU 监控 ====================

async def gpu_status(server_id: str) -> str:
    """获取 GPU 状态"""
    from server.services.ssh_manager import ssh_manager
    result = await ssh_manager.get_gpu_status(server_id)
    if not result["available"]:
        return "GPU not available"
    lines = []
    for gpu in result["gpus"]:
        lines.append(f"GPU {gpu['index']}: {gpu['name']} | {gpu['memory_used_mb']}/{gpu['memory_total_mb']}MB | {gpu['utilization_percent']}% | {gpu['temperature_c']}°C")
    return '\n'.join(lines)



# ==================== Semantic Scholar 搜索 ====================

async def semantic_scholar_search(query: str, max_results: int = 10) -> str:
    """搜索 Semantic Scholar 论文（带引用数和摘要）"""
    try:
        import httpx
        s2_key = os.environ.get("S2_API_KEY", "")
        headers = {"x-api-key": s2_key} if s2_key else {}
        url = f"https://api.semanticscholar.org/graph/v1/paper/search?query={query}&limit={max_results}&fields=title,year,citationCount,abstract,authors,venue"

        # 限速：确保距上次调用至少 1 秒
        import time
        last_call = getattr(semantic_scholar_search, '_last_call', 0)
        elapsed = time.time() - last_call
        if elapsed < 1.0:
            await asyncio.sleep(1.0 - elapsed)
        semantic_scholar_search._last_call = time.time()

        async with httpx.AsyncClient(follow_redirects=True) as client:
            from ..remote_errors import read_only_get
            resp = await read_only_get(client, url, service="semantic_scholar", headers=headers, timeout=15)
            data = resp.json()
            results = []
            for paper in data.get("data", []):
                title = paper.get("title", "?")
                year = paper.get("year", "?")
                citations = paper.get("citationCount", 0)
                venue = paper.get("venue", "")
                authors = ", ".join(a.get("name", "") for a in paper.get("authors", [])[:3])
                abstract = (paper.get("abstract") or "")[:150]
                results.append(f"[{year}] {title}\n  Authors: {authors}\n  Venue: {venue} | Citations: {citations}\n  {abstract}")
            return '\n\n'.join(results) if results else "No results found"
    except Exception as e:
        from ..remote_errors import RemoteCallError
        if isinstance(e, RemoteCallError):
            raise
        raise RuntimeError(f"Semantic Scholar search failed: {e}") from e


# ==================== DBLP/CrossRef 引用验证 ====================

async def verify_citation(title: str, authors: str = "", year: str = "") -> str:
    """验证一条引用是否真实存在（查 CrossRef + DBLP）"""
    import httpx
    results = []

    # CrossRef 验证
    try:
        async with httpx.AsyncClient() as client:
            query = f"{title} {authors}".strip()
            resp = await client.get(f"https://api.crossref.org/works?query={query}&rows=3", timeout=10)
            if resp.status_code == 200:
                items = resp.json().get("message", {}).get("items", [])
                for item in items[:2]:
                    cr_title = item.get("title", [""])[0]
                    cr_doi = item.get("DOI", "")
                    cr_year = str(item.get("published", {}).get("date-parts", [[""]])[0][0])
                    results.append(f"[CrossRef] {cr_title} (DOI: {cr_doi}, year: {cr_year})")
    except Exception as exc:
        logger.debug("CrossRef citation lookup failed", error=str(exc))
        results.append("[CrossRef] lookup failed")

    # DBLP 验证
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"https://dblp.org/search/publ/api?q={title}&format=json&h=3", timeout=10)
            if resp.status_code == 200:
                hits = resp.json().get("result", {}).get("hits", {}).get("hit", [])
                for hit in hits[:2]:
                    info = hit.get("info", {})
                    dblp_title = info.get("title", "")
                    dblp_venue = info.get("venue", "")
                    dblp_year = info.get("year", "")
                    results.append(f"[DBLP] {dblp_title} ({dblp_venue}, {dblp_year})")
    except Exception as exc:
        logger.debug("DBLP citation lookup failed", error=str(exc))
        results.append("[DBLP] lookup failed")

    if not results:
        return f"UNVERIFIED: No matching records for '{title}'"
    return '\n'.join(results)


# ==================== 审计状态机 ====================

async def audit_verdict(project_path: str, layer: str, verdict: str, details: str = "") -> str:
    """记录审计裁决到项目状态文件

    layer: experiment | result-claim | paper-claim | citation | kill-argument
    verdict: PASS | WARN | FAIL | NOT_APPLICABLE | BLOCKED | ERROR
    """
    import json
    from pathlib import Path

    valid_layers = ["experiment", "result-claim", "paper-claim", "citation", "kill-argument"]
    valid_verdicts = ["PASS", "WARN", "FAIL", "NOT_APPLICABLE", "BLOCKED", "ERROR"]

    if layer not in valid_layers:
        return f"Invalid layer: {layer}. Must be one of {valid_layers}"
    if verdict not in valid_verdicts:
        return f"Invalid verdict: {verdict}. Must be one of {valid_verdicts}"

    # 读取或创建审计状态文件
    audit_file = Path(project_path) / ".merak" / "audit_state.json"
    audit_file.parent.mkdir(parents=True, exist_ok=True)
    with path_lock(audit_file):
        if audit_file.exists():
            try:
                state = json.loads(audit_file.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                raise RuntimeError(
                    f"Audit state is unreadable or corrupt: {audit_file}"
                ) from exc
            if not isinstance(state, dict) or not isinstance(
                state.get("layers"), dict
            ):
                raise RuntimeError(
                    f"Audit state has an invalid object structure: {audit_file}"
                )
        else:
            state = {"layers": {}, "overall": "PENDING"}

        # 更新该层裁决
        import time
        state["layers"][layer] = {
            "verdict": verdict,
            "details": details[:500],
            "timestamp": time.time(),
        }

        # 计算总体状态
        verdicts = [
            value.get("verdict")
            for value in state["layers"].values()
            if isinstance(value, dict)
        ]
        if "FAIL" in verdicts or "ERROR" in verdicts:
            state["overall"] = "BLOCKED"
        elif "BLOCKED" in verdicts:
            state["overall"] = "BLOCKED"
        elif (
            all(value in ("PASS", "NOT_APPLICABLE") for value in verdicts)
            and len(verdicts) >= 4
        ):
            state["overall"] = "PASS"
        else:
            state["overall"] = "IN_PROGRESS"

        atomic_write_json(audit_file, state)
    return f"Audit layer '{layer}' = {verdict}. Overall: {state['overall']}"


async def audit_status(project_path: str) -> str:
    """读取当前审计状态"""
    import json
    from pathlib import Path

    audit_file = Path(project_path) / ".merak" / "audit_state.json"
    if not audit_file.exists():
        return "No audit state found. Run /experiment-audit first."

    state = json.loads(audit_file.read_text(encoding='utf-8'))
    lines = [f"Overall: {state.get('overall', '?')}"]
    for layer, data in state.get("layers", {}).items():
        lines.append(f"  {layer}: {data['verdict']}")
        if data.get("details"):
            lines.append(f"    {data['details'][:100]}")
    return '\n'.join(lines)


# ==================== Research Wiki ====================

async def wiki_read(project_path: str, key: str = "") -> str:
    """读取 Research Wiki 内容"""
    from pathlib import Path

    wiki_dir = Path(project_path) / ".merak" / "wiki"
    if not wiki_dir.exists():
        return "Wiki is empty. Use wiki_write to add entries."

    if key:
        safe_key = str(key or "").strip()
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,120}", safe_key):
            raise ValueError(
                "Wiki key may contain only letters, digits, dot, underscore, and hyphen"
            )
        entry_file = (wiki_dir / f"{safe_key}.md").resolve()
        if not entry_file.is_relative_to(wiki_dir.resolve()):
            raise ValueError("Wiki entry path leaves the project wiki directory")
        if entry_file.exists():
            return entry_file.read_text(encoding='utf-8')
        return f"Wiki entry '{key}' not found."

    # 列出所有条目
    entries = sorted(wiki_dir.glob("*.md"))
    if not entries:
        return "Wiki is empty."
    lines = ["Research Wiki entries:"]
    for e in entries:
        first_line = e.read_text(encoding='utf-8').splitlines()[0] if e.stat().st_size > 0 else ""
        lines.append(f"  - {e.stem}: {first_line[:80]}")
    return '\n'.join(lines)


async def wiki_write(project_path: str, key: str, content: str) -> str:
    """写入/更新 Research Wiki 条目"""
    from pathlib import Path

    wiki_dir = Path(project_path) / ".merak" / "wiki"
    wiki_dir.mkdir(parents=True, exist_ok=True)

    safe_key = str(key or "").strip()
    if not safe_key or not re.fullmatch(r"[A-Za-z0-9_.-]{1,120}", safe_key):
        raise ValueError(
            "Wiki key may contain only letters, digits, dot, underscore, and hyphen"
        )
    entry_file = (wiki_dir / f"{safe_key}.md").resolve()
    if not entry_file.is_relative_to(wiki_dir.resolve()):
        raise ValueError("Wiki entry path leaves the project wiki directory")
    atomic_write_text(entry_file, content)
    return f"Wiki entry '{key}' written ({len(content)} chars)"


# ==================== 专利工具 ====================

async def patent_search(query: str, max_results: int = 15) -> str:
    """搜索专利"""
    from server.services.patent_tools import patent_tools
    results = await patent_tools.search_patents(query, max_results)
    if not results:
        return "No patents found. Ensure SERPAPI_KEY or EPO_OPS_KEY is configured."
    output = []
    for r in results:
        output.append(f"- [{r.patent_id}] {r.title} ({r.filing_date}) by {r.applicant}")
        if r.abstract:
            output.append(f"  Abstract: {r.abstract[:150]}...")
    return "\n".join(output)


async def patent_prior_art(invention_description: str, claims: list[str] = None) -> str:
    """分析前引技术"""
    from server.services.patent_tools import patent_tools
    analysis = await patent_tools.analyze_prior_art(invention_description, claims or [])
    parts = [
        "## Prior Art Analysis",
        f"Query: {analysis.query[:100]}",
        f"Patents found: {len(analysis.patents_found)}",
        "",
        "### Novelty Assessment",
        analysis.novelty_assessment,
        "",
        "### Overlap Summary",
        analysis.overlap_summary or "No significant overlap detected.",
        "",
        "### Suggested Differentiation",
    ]
    for s in analysis.suggested_differentiation:
        parts.append(f"- {s}")
    return "\n".join(parts)


async def patent_claims_template(title: str, components: list[str], method_steps: list[str]) -> str:
    """生成权利要求书模板"""
    from server.services.patent_tools import patent_tools
    return patent_tools.generate_claims_template(title, components, method_steps)


# ==================== Meta-Optimize ====================

async def meta_optimize_propose(
    project_path: str, skill_name: str, original_content: str, proposed_content: str, description: str
) -> str:
    """提出技能自我优化修改"""
    from server.services.meta_optimize import get_meta_optimize_gate
    gate = get_meta_optimize_gate(project_path)
    result = gate.propose_mutation(skill_name, original_content, proposed_content, description)
    if result["accepted"]:
        return f"Mutation proposed: {result['mutation_id']}\nDiff: {result.get('diff_summary', '')}\nStatus: Awaiting human approval."
    else:
        raise ValueError(f"Mutation REJECTED: {result['reason']}")


# ==================== 图表生成 ====================
