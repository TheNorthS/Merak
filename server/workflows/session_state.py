"""
Session 恢复 — 断点续跑

Workflow 执行时定期保存状态到 .merak/state.json。
如果进程崩溃或用户关闭 IDE，下次启动时可以从上次断点恢复。
"""

import json
import time
from pathlib import Path
from typing import Optional

import structlog

from ..utils.atomic_write import atomic_write_json, path_lock

logger = structlog.get_logger()


class SessionState:
    """可序列化的 workflow 执行状态"""

    def __init__(self, project_path: str):
        self.project_path = str(Path(project_path or ".").expanduser().resolve())
        self._state_file = Path(self.project_path) / ".merak" / "state.json"

    def save(self, run_id: str, nodes_status: dict, current_node: str, config: dict):
        """保存当前状态"""
        self._state_file.parent.mkdir(parents=True, exist_ok=True)
        state = {
            "run_id": run_id,
            "nodes_status": nodes_status,  # {node_id: "completed"|"running"|"idle"|"failed"}
            "current_node": current_node,
            "config": config,
            "saved_at": time.time(),
            "resumable": True,
        }
        with path_lock(self._state_file):
            if self._state_file.exists():
                try:
                    existing = json.loads(
                        self._state_file.read_text(encoding="utf-8")
                    )
                except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                    raise RuntimeError(
                        "Workflow session state is unreadable or corrupt; "
                        f"refusing to overwrite it: {self._state_file}"
                    ) from exc
                if not isinstance(existing, dict):
                    raise RuntimeError(
                        "Workflow session state root must be a JSON object; "
                        f"refusing to overwrite it: {self._state_file}"
                    )
            atomic_write_json(self._state_file, state)
        logger.debug("Session state saved", run_id=run_id, node=current_node)

    def load(self) -> Optional[dict]:
        """加载已保存的状态（如果有）"""
        if not self._state_file.exists():
            return None
        try:
            with path_lock(self._state_file):
                state = json.loads(self._state_file.read_text(encoding='utf-8'))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise RuntimeError(
                "Workflow session state is unreadable or corrupt; refusing "
                f"to replace it: {self._state_file}"
            ) from exc
        if not isinstance(state, dict):
            raise RuntimeError(
                "Workflow session state root must be a JSON object; refusing "
                f"to replace it: {self._state_file}"
            )
        if state.get("resumable"):
            nodes_status = state.get("nodes_status")
            config = state.get("config")
            if not isinstance(nodes_status, dict) or not isinstance(config, dict):
                raise RuntimeError(
                    "Workflow session state is missing valid nodes_status/config: "
                    f"{self._state_file}"
                )
            return state
        return None

    def clear(self):
        """清除状态（workflow 正常完成时调用）"""
        with path_lock(self._state_file):
            self._state_file.unlink(missing_ok=True)

    def has_resumable_state(self) -> bool:
        """是否有可恢复的状态"""
        state = self.load()
        return state is not None and state.get("resumable", False)

    def get_completed_nodes(self) -> list[str]:
        """获取已完成的节点列表（恢复时跳过这些）"""
        state = self.load()
        if not state:
            return []
        return [nid for nid, status in state.get("nodes_status", {}).items() if status == "completed"]
