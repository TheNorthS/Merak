"""
项目记忆系统 — 让 Agent 记住每个项目的上下文

每个项目维护一个 MEMORY.md 文件，记录：
- 研究方向和目标
- 已完成的工作流节点
- 关键发现和决策
- 实验结果摘要
- 论文结构状态

Agent 每次启动时读取项目记忆，执行完成后更新。
"""

import json
import threading
import time
from pathlib import Path
from dataclasses import dataclass, field

import structlog

from ..utils.atomic_write import atomic_write_json, atomic_write_text, path_lock

logger = structlog.get_logger()

MEMORY_DIR = ".merak"
MEMORY_FILE = "memory.json"
CONTEXT_FILE = "CONTEXT.md"


@dataclass
class ProjectMemoryEntry:
    """单条记忆"""
    key: str
    content: str
    source: str  # "workflow" | "chat" | "user"
    timestamp: float = field(default_factory=time.time)


@dataclass
class ProjectMemory:
    """项目级记忆"""
    project_path: str
    research_direction: str = ""
    entries: list[ProjectMemoryEntry] = field(default_factory=list)
    workflow_history: list[dict] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    last_accessed: float = field(default_factory=time.time)


class ProjectMemoryManager:
    """管理所有项目的记忆"""

    def __init__(self):
        self._cache: dict[str, ProjectMemory] = {}
        self._cache_lock = threading.RLock()

    def _memory_path(self, project_path: str) -> Path:
        return Path(project_path) / MEMORY_DIR / MEMORY_FILE

    def _context_path(self, project_path: str) -> Path:
        return Path(project_path) / MEMORY_DIR / CONTEXT_FILE

    def load(self, project_path: str) -> ProjectMemory:
        """加载项目记忆（从磁盘 or 缓存）"""
        with self._cache_lock:
            if project_path in self._cache:
                mem = self._cache[project_path]
                mem.last_accessed = time.time()
                return mem

        path = self._memory_path(project_path)
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(data, dict):
                    raise ValueError("memory root must be a JSON object")
                raw_entries = data.get("entries", [])
                raw_history = data.get("workflow_history", [])
                if not isinstance(raw_entries, list) or not isinstance(raw_history, list):
                    raise ValueError("memory entries/history must be arrays")
                mem = ProjectMemory(
                    project_path=project_path,
                    research_direction=data.get("research_direction", ""),
                    entries=[
                        ProjectMemoryEntry(**e)
                        for e in raw_entries
                        if isinstance(e, dict)
                    ],
                    workflow_history=[
                        item for item in raw_history if isinstance(item, dict)
                    ],
                    created_at=data.get("created_at", time.time()),
                    last_accessed=time.time(),
                )
                with self._cache_lock:
                    self._cache[project_path] = mem
                return mem
            except Exception as e:
                raise RuntimeError(f"Project memory is unreadable: {path}") from e

        # 新项目
        mem = ProjectMemory(project_path=project_path)
        with self._cache_lock:
            self._cache[project_path] = mem
        return mem

    def save(self, project_path: str) -> None:
        """持久化到磁盘"""
        with self._cache_lock:
            mem = self._cache.get(project_path)
        if not mem:
            return

        path = self._memory_path(project_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        data = {
            "research_direction": mem.research_direction,
            "entries": [
                {"key": e.key, "content": e.content, "source": e.source, "timestamp": e.timestamp}
                for e in mem.entries
            ],
            "workflow_history": mem.workflow_history[-20:],  # 只保留最近 20 条
            "created_at": mem.created_at,
        }
        with path_lock(path):
            if path.exists():
                try:
                    existing = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                    raise RuntimeError(
                        f"Refusing to overwrite unreadable project memory: {path}"
                    ) from exc
                if not isinstance(existing, dict):
                    raise RuntimeError(
                        f"Refusing to overwrite non-object project memory: {path}"
                    )
            atomic_write_json(path, data)

        # 同时写一份人类可读的 CONTEXT.md
        self._write_context_md(project_path, mem)

    def add_entry(self, project_path: str, key: str, content: str, source: str = "workflow") -> None:
        """添加/更新一条记忆"""
        with self._cache_lock:
            mem = self.load(project_path)
            # 同 key 覆盖
            mem.entries = [e for e in mem.entries if e.key != key]
            mem.entries.append(ProjectMemoryEntry(key=key, content=content, source=source))
            # 限制总条数
            if len(mem.entries) > 100:
                mem.entries = mem.entries[-100:]
            self.save(project_path)

    def record_workflow_run(self, project_path: str, run_summary: dict) -> None:
        """记录一次 workflow 执行"""
        with self._cache_lock:
            mem = self.load(project_path)
            mem.workflow_history.append({
                **run_summary,
                "timestamp": time.time(),
            })
            self.save(project_path)

    def set_research_direction(self, project_path: str, direction: str) -> None:
        """设置研究方向"""
        with self._cache_lock:
            mem = self.load(project_path)
            mem.research_direction = direction
            self.save(project_path)

    def get_context_for_agent(self, project_path: str) -> str:
        """生成给 Agent 的上下文摘要"""
        mem = self.load(project_path)

        lines = [f"## 项目记忆 ({project_path})"]
        if mem.research_direction:
            lines.append(f"\n### 研究方向\n{mem.research_direction}")

        if mem.workflow_history:
            lines.append("\n### 最近工作流执行")
            for run in mem.workflow_history[-5:]:
                status = run.get("status", "?")
                nodes = run.get("nodes_completed", [])
                lines.append(f"- [{status}] {', '.join(nodes)}")

        if mem.entries:
            lines.append("\n### 关键记忆")
            # 按时间倒序取最近 20 条
            recent = sorted(mem.entries, key=lambda e: e.timestamp, reverse=True)[:20]
            for entry in recent:
                lines.append(f"- **{entry.key}**: {entry.content[:200]}")

        return "\n".join(lines)

    def _write_context_md(self, project_path: str, mem: ProjectMemory) -> None:
        """写人类可读的 CONTEXT.md"""
        ctx_path = self._context_path(project_path)
        lines = [
            "# MERAK Project Context",
            "",
            f"> Auto-generated by Merak. Last updated: {time.strftime('%Y-%m-%d %H:%M')}",
            "",
        ]
        if mem.research_direction:
            lines.extend(["## Research Direction", "", mem.research_direction, ""])

        if mem.workflow_history:
            lines.extend(["## Workflow History", ""])
            for run in mem.workflow_history[-10:]:
                ts = time.strftime('%m/%d %H:%M', time.localtime(run.get("timestamp", 0)))
                lines.append(f"- `{ts}` [{run.get('status', '?')}] nodes: {run.get('nodes_completed', [])}")
            lines.append("")

        if mem.entries:
            lines.extend(["## Key Findings", ""])
            for entry in mem.entries[-30:]:
                lines.append(f"### {entry.key}")
                lines.append(f"{entry.content[:500]}")
                lines.append("")

        ctx_path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(ctx_path, "\n".join(lines))


# 全局单例
project_memory = ProjectMemoryManager()
