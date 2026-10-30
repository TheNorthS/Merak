"""
Meta-Optimize 自进化 Gate

控制 MERAK 技能自我优化的安全阀门：
1. Agent 提出 skill prompt 修改建议
2. 变更进入 pending 队列
3. 人工审批、合同验证及运行时加载成功后生效
4. 所有变更可回滚

不允许的变更：
- 删除安全检查
- 修改 audit 逻辑
- 绕过 human-in-the-loop
"""

import json
import time
import hashlib
import difflib
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, field
from enum import Enum

import structlog

from ..utils.atomic_write import atomic_write_json, atomic_write_text, path_lock
from .meta_optimize_application import (
    mutation_transaction, refresh_skill, valid_skill_identity, validate_skill_revision,
)

logger = structlog.get_logger()


def _read_observations(path: Path) -> dict:
    if not path.exists():
        return {"signatures": {}}
    try:
        observations = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Meta-optimize observations are unreadable: {path}") from exc
    if not isinstance(observations, dict):
        raise RuntimeError(f"Meta-optimize observations root must be an object: {path}")
    return observations


class MutationStatus(str, Enum):
    PENDING = "pending"        # 等待审批
    APPROVED = "approved"      # 已批准
    REJECTED = "rejected"      # 已拒绝
    APPLIED = "applied"        # 已应用
    ROLLED_BACK = "rolled_back"  # 已回滚


@dataclass
class SkillMutation:
    """一次技能修改提案"""
    id: str
    skill_name: str
    description: str        # 为什么要改
    diff_summary: str       # 改了什么（人类可读）
    original_content: str   # 修改前的完整内容
    proposed_content: str   # 修改后的完整内容
    status: MutationStatus = MutationStatus.PENDING
    proposed_at: float = field(default_factory=time.time)
    decided_at: Optional[float] = None
    decided_by: str = ""    # "human" | "auto_test"
    metrics_before: dict = field(default_factory=dict)
    metrics_after: dict = field(default_factory=dict)
    source_path: str = ""
    original_sha256: str = ""


# 不允许修改的关键字（安全边界）
FORBIDDEN_REMOVALS = [
    "human-in-the-loop",
    "human approval",
    "audit_verdict",
    "BLOCKED",
    "safety",
    "verification required",
]


class MetaOptimizeGate:
    """技能自进化安全门"""

    def __init__(self, project_path: str = "."):
        self._base_path = Path(project_path) / ".merak" / "meta_optimize"
        self._mutations: dict[str, SkillMutation] = {}
        self._load_state()

    def _state_file(self) -> Path:
        return self._base_path / "mutations.json"

    def _backup_dir(self) -> Path:
        return self._base_path / "backups"

    def _load_state(self):
        """加载已有的 mutation 记录"""
        state_file = self._state_file()
        if state_file.exists():
            try:
                data = json.loads(state_file.read_text(encoding='utf-8'))
                if not isinstance(data, dict) or not isinstance(data.get("mutations", []), list):
                    raise ValueError("meta-optimize state root/mutations has an invalid type")
                for m in data.get("mutations", []):
                    if not isinstance(m, dict):
                        raise ValueError("meta-optimize mutation record must be an object")
                    m["status"] = MutationStatus(m.get("status", "pending"))
                    mutation = SkillMutation(**m)
                    self._mutations[mutation.id] = mutation
            except Exception as e:
                raise RuntimeError(
                    f"Meta-optimize state is unreadable: {state_file}"
                ) from e

    def _save_state(self):
        """持久化状态"""
        self._base_path.mkdir(parents=True, exist_ok=True)
        data = {
            "mutations": [
                {
                    "id": m.id,
                    "skill_name": m.skill_name,
                    "description": m.description,
                    "diff_summary": m.diff_summary,
                    "original_content": m.original_content,
                    "proposed_content": m.proposed_content,
                    "status": m.status.value,
                    "proposed_at": m.proposed_at,
                    "decided_at": m.decided_at,
                    "decided_by": m.decided_by,
                    "metrics_before": m.metrics_before,
                    "metrics_after": m.metrics_after,
                    "source_path": m.source_path,
                    "original_sha256": m.original_sha256,
                }
                for m in self._mutations.values()
            ]
        }
        state_file = self._state_file()
        with path_lock(state_file):
            if state_file.exists():
                try:
                    existing = json.loads(state_file.read_text(encoding="utf-8"))
                except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                    raise RuntimeError(
                        f"Refusing to overwrite unreadable meta-optimize state: {state_file}"
                    ) from exc
                if not isinstance(existing, dict):
                    raise RuntimeError(
                        f"Refusing to overwrite invalid meta-optimize state: {state_file}"
                    )
            atomic_write_json(state_file, data)

    @mutation_transaction
    def propose_mutation(
        self,
        skill_name: str,
        original_content: str,
        proposed_content: str,
        description: str,
        metrics_before: Optional[dict] = None,
    ) -> dict:
        """Agent 提出 skill 修改提案

        Returns:
            {"accepted": bool, "mutation_id": str, "reason": str}
        """
        if not valid_skill_identity(skill_name):
            return {"accepted": False, "mutation_id": "", "reason": "Invalid skill identity"}
        skill_path = self._find_skill_file(skill_name)
        if not skill_path:
            return {"accepted": False, "mutation_id": "", "reason": "Canonical skill not found"}
        try:
            validate_skill_revision(skill_path, original_content, proposed_content)
        except ValueError as exc:
            return {"accepted": False, "mutation_id": "", "reason": str(exc)}
        # 安全检查：不允许删除关键安全内容
        for keyword in FORBIDDEN_REMOVALS:
            if keyword.lower() in original_content.lower() and keyword.lower() not in proposed_content.lower():
                logger.warning("Meta-optimize: blocked removal of safety keyword",
                             skill=skill_name, keyword=keyword)
                return {
                    "accepted": False,
                    "mutation_id": "",
                    "reason": f"Cannot remove safety-critical content: '{keyword}'",
                }

        # 生成 mutation ID
        content_hash = hashlib.sha256(proposed_content.encode()).hexdigest()[:8]
        mutation_id = f"mut_{skill_name}_{content_hash}"
        if mutation_id in self._mutations:
            previous = self._mutations[mutation_id]
            return {"accepted": previous.status == MutationStatus.PENDING,
                    "mutation_id": mutation_id, "reason": f"Existing mutation is {previous.status.value}"}

        # 生成 diff 摘要
        diff_summary = self._generate_diff_summary(original_content, proposed_content)

        skill_path = self._find_skill_file(skill_name)
        source_path = str(skill_path.resolve()) if skill_path else ""
        original_sha256 = hashlib.sha256(original_content.encode("utf-8")).hexdigest()
        if skill_path and skill_path.is_file():
            current = skill_path.read_text(encoding="utf-8", errors="replace")
            if current != original_content:
                return {
                    "accepted": False,
                    "mutation_id": "",
                    "reason": "Original content does not match the current canonical skill file",
                }

        mutation = SkillMutation(
            id=mutation_id,
            skill_name=skill_name,
            description=description,
            diff_summary=diff_summary,
            original_content=original_content,
            proposed_content=proposed_content,
            metrics_before=metrics_before or {},
            source_path=source_path,
            original_sha256=original_sha256,
        )

        self._mutations[mutation_id] = mutation
        self._save_state()

        logger.info("Skill mutation proposed",
                   id=mutation_id, skill=skill_name, description=description[:100])

        return {
            "accepted": True,
            "mutation_id": mutation_id,
            "reason": "Mutation queued for approval",
            "diff_summary": diff_summary,
        }

    @mutation_transaction
    def approve_mutation(self, mutation_id: str, decided_by: str = "human") -> dict:
        """批准并应用 mutation"""
        mutation = self._mutations.get(mutation_id)
        if not mutation:
            return {"success": False, "error": "Mutation not found"}

        if mutation.status != MutationStatus.PENDING:
            return {"success": False, "error": f"Mutation is {mutation.status.value}, not pending"}

        # 应用修改
        skill_path = self._find_skill_file(mutation.skill_name)
        if skill_path and skill_path.exists() and str(skill_path.resolve()) == mutation.source_path:
            current_content = skill_path.read_text(encoding="utf-8", errors="replace")
            current_sha256 = hashlib.sha256(current_content.encode("utf-8")).hexdigest()
            if mutation.original_sha256 and current_sha256 != mutation.original_sha256:
                return {
                    "success": False,
                    "error": "Mutation is stale because the canonical skill changed after proposal creation",
                }
            self._backup_skill(mutation.skill_name, mutation.original_content)
            atomic_write_text(skill_path, mutation.proposed_content)
            try:
                refresh_skill(skill_path)
            except ValueError as exc:
                atomic_write_text(skill_path, current_content)
                return {"success": False, "error": str(exc)}
            mutation.status = MutationStatus.APPLIED
        else:
            return {"success": False, "error": "Canonical skill is missing or its location changed"}

        mutation.decided_at = time.time()
        mutation.decided_by = decided_by
        self._save_state()

        logger.info("Skill mutation approved",
                   id=mutation_id, skill=mutation.skill_name, by=decided_by)

        return {"success": True, "status": "applied", "skill": mutation.skill_name}

    @mutation_transaction
    def reject_mutation(self, mutation_id: str, reason: str = "") -> dict:
        """拒绝 mutation"""
        mutation = self._mutations.get(mutation_id)
        if not mutation:
            return {"success": False, "error": "Mutation not found"}

        if mutation.status != MutationStatus.PENDING:
            return {"success": False, "error": f"Cannot reject a {mutation.status.value} mutation"}
        mutation.status = MutationStatus.REJECTED
        mutation.decided_at = time.time()
        mutation.decided_by = "human"
        self._save_state()

        return {"success": True, "status": "rejected"}

    @mutation_transaction
    def rollback_mutation(self, mutation_id: str) -> dict:
        """回滚已应用的 mutation"""
        mutation = self._mutations.get(mutation_id)
        if not mutation:
            return {"success": False, "error": "Mutation not found"}

        if mutation.status != MutationStatus.APPLIED:
            return {"success": False, "error": f"Cannot rollback: status is {mutation.status.value}"}

        # 恢复原始内容
        skill_path = self._find_skill_file(mutation.skill_name)
        if not skill_path or not skill_path.is_file() or str(skill_path.resolve()) != mutation.source_path:
            return {"success": False, "error": "Canonical skill is missing or its location changed"}
        if skill_path:
            current = skill_path.read_text(encoding="utf-8", errors="strict")
            proposed_sha256 = hashlib.sha256(
                mutation.proposed_content.encode("utf-8")
            ).hexdigest()
            current_sha256 = hashlib.sha256(current.encode("utf-8")).hexdigest()
            if current_sha256 != proposed_sha256:
                return {
                    "success": False,
                    "error": "Cannot rollback because the canonical skill changed after this mutation was applied",
                }
            atomic_write_text(skill_path, mutation.original_content)
            refresh_skill(skill_path)

        mutation.status = MutationStatus.ROLLED_BACK
        self._save_state()

        logger.info("Skill mutation rolled back", id=mutation_id, skill=mutation.skill_name)
        return {"success": True, "status": "rolled_back"}

    def list_mutations(self, status: Optional[str] = None) -> list[dict]:
        """列出所有 mutations"""
        with path_lock(self._state_file()):
            self._mutations.clear()
            self._load_state()
        mutations = list(self._mutations.values())
        if status:
            mutations = [m for m in mutations if m.status.value == status]

        return [
            {
                "id": m.id,
                "skill_name": m.skill_name,
                "description": m.description,
                "diff_summary": m.diff_summary,
                "diff": "\n".join(difflib.unified_diff(m.original_content.splitlines(),
                    m.proposed_content.splitlines(), fromfile="current/SKILL.md", tofile="proposed/SKILL.md", lineterm="")),
                "status": m.status.value,
                "proposed_at": m.proposed_at,
                "decided_at": m.decided_at,
                "decided_by": m.decided_by,
                "source_path": m.source_path,
                "original_sha256": m.original_sha256,
            }
            for m in sorted(mutations, key=lambda x: x.proposed_at, reverse=True)
        ]

    def _backup_skill(self, skill_name: str, content: str):
        """备份 skill 原始内容"""
        backup_dir = self._backup_dir()
        backup_dir.mkdir(parents=True, exist_ok=True)
        timestamp = int(time.time())
        backup_file = backup_dir / f"{skill_name}_{timestamp}.md"
        atomic_write_text(backup_file, content)

    def _find_skill_file(self, skill_name: str) -> Optional[Path]:
        """查找 skill 文件路径"""
        if not valid_skill_identity(skill_name):
            return None
        from .skill_registry import skill_registry

        metadata = skill_registry.get_skill(skill_name)
        if metadata and metadata.file_path:
            path = Path(metadata.file_path)
            if path.is_file():
                return path
        repository_root = Path(__file__).resolve().parents[2]
        for skills_dir in (repository_root / "merak-skills", repository_root / "skills"):
            candidate = skills_dir / skill_name / "SKILL.md"
            if candidate.is_file():
                return candidate
        return None

    def observe_workflow_failure(
        self,
        skill_name: str,
        signature: str,
        run_id: str,
        details: str = "",
    ) -> dict:
        """Create a pending guardrail only after a failure repeats across runs."""
        observations_path = self._base_path / "observations.json"
        self._base_path.mkdir(parents=True, exist_ok=True)
        with path_lock(observations_path):
            observations = _read_observations(observations_path)
            signatures = observations.setdefault("signatures", {})
            if not isinstance(signatures, dict):
                raise RuntimeError(
                    f"Meta-optimize signatures must be an object: {observations_path}"
                )
            key = hashlib.sha256(
                f"{skill_name}:{signature}".encode("utf-8")
            ).hexdigest()[:16]
            record = signatures.setdefault(key, {
                "skill_name": skill_name,
                "signature": signature,
                "runs": [],
                "details": [],
            })
            if not isinstance(record, dict):
                raise RuntimeError(
                    f"Meta-optimize observation record is invalid: {observations_path}"
                )
            if not isinstance(record.get("runs"), list) or not isinstance(
                record.get("details"), list
            ):
                raise RuntimeError(
                    f"Meta-optimize observation lists are invalid: {observations_path}"
                )
            if run_id not in record["runs"]:
                record["runs"].append(run_id)
            if details and details not in record["details"]:
                record["details"].append(details[:1000])
            atomic_write_json(observations_path, observations)
        count = len(record["runs"])
        if count < 2:
            return {"proposed": False, "observations": count, "reason": "requires repeated evidence"}

        skill_path = self._find_skill_file(skill_name)
        if not skill_path:
            return {"proposed": False, "observations": count, "reason": "canonical skill not found"}
        original = skill_path.read_text(encoding="utf-8", errors="replace")
        marker = f"merak-failure-signature:{key}"
        if marker in original:
            return {"proposed": False, "observations": count, "reason": "guardrail already present"}
        appendix = (
            "\n\n## MERAK Observed Failure Guardrail\n"
            f"<!-- {marker} -->\n"
            f"- Repeated failure pattern: {signature[:500]}\n"
            "- Before declaring this skill complete, explicitly test for this pattern and preserve the failing evidence.\n"
            "- Do not bypass an acceptance, safety, citation, or human-approval gate to make the pattern disappear.\n"
        )
        proposal = self.propose_mutation(
            skill_name=skill_name,
            original_content=original,
            proposed_content=original.rstrip() + appendix,
            description=(
                f"Repeated workflow failure observed in {count} runs ({', '.join(record['runs'][-3:])}); "
                "propose a bounded prevention/checking guardrail."
            ),
            metrics_before={"failure_observations": count, "signature_key": key},
        )
        return {"proposed": bool(proposal.get("accepted")), "observations": count, **proposal}

    def _generate_diff_summary(self, original: str, proposed: str) -> str:
        """生成简洁的 diff 摘要"""
        orig_lines = set(original.splitlines())
        prop_lines = set(proposed.splitlines())

        added = prop_lines - orig_lines
        removed = orig_lines - prop_lines

        parts = []
        if removed:
            parts.append(f"-{len(removed)} lines removed")
        if added:
            parts.append(f"+{len(added)} lines added")

        # 提取前几个显著变化
        significant_adds = [line.strip() for line in added if len(line.strip()) > 20][:3]
        if significant_adds:
            parts.append(f"New content includes: {significant_adds[0][:60]}...")

        return " | ".join(parts) if parts else "No significant changes"


# 全局实例（延迟初始化，需要 project_path）
_gate_instances: dict[str, MetaOptimizeGate] = {}


def get_meta_optimize_gate(project_path: str) -> MetaOptimizeGate:
    """获取或创建项目对应的 MetaOptimizeGate"""
    project_path = str(Path(project_path).expanduser().resolve())
    if project_path not in _gate_instances:
        _gate_instances[project_path] = MetaOptimizeGate(project_path)
    return _gate_instances[project_path]
