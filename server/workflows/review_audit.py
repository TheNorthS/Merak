r"""
跨模型审稿协议 + 5层科学审计链 + 独立证明审计

核心不变量：Executor 与 Reviewer 使用角色隔离的独立会话；模型可相同

审稿循环：
- 最多 4 轮
- 每轮：Review → Parse → (Debate) → Fix → Wait → Document
- 停止条件：score ≥ 6 AND verdict ∈ {ready, almost}

5层审计链：
- Layer 1: 实验审计（代码诚实性）
- Layer 2: 结果→声明（声明是否跟随数据）
- Layer 3: 数字审计（论文报告数字和实验结果一致）
- Layer 4: 引用审计（所有 \cite{} 有效）
- Layer 5: Kill Argument（最强拒稿论点）

独立证明审计：
- /proof-checker: 有定理/引理/命题/推论/证明环境时执行独立模型审计
- 无上述形式化环境时仍写出 NOT_APPLICABLE 机器可读结果，禁止静默跳过
"""

import hashlib
import json
import re
import time
import uuid
from typing import Any, Optional
from pathlib import Path

import structlog

from ..agent import model_router, ModelRole
from .review_models import (
    AuditResult as AuditResult,
    AuditSourceChangedError as AuditSourceChangedError,
    NATIVE_VISUAL_REVIEW_TRANSPORTS as NATIVE_VISUAL_REVIEW_TRANSPORTS,
    ReviewRound as ReviewRound,
    ReviewState as ReviewState,
    Verdict as Verdict,
)
from .review_visuals import ReviewVisualsMixin
from .review_protocol import ReviewProtocolMixin
from .audit_protocol import AuditProtocolMixin
from .audit_layers import AuditLayersMixin
from ..utils.atomic_write import (
    atomic_write_json,
    atomic_write_text,
)

logger = structlog.get_logger()

# Review calls have their own bounded budgets because this coordinator bypasses
# the ordinary workflow-node agent wrapper. These are platform policy values,
# not user-facing knobs.
REVIEW_MODEL_CALL_TIMEOUT_SECONDS = 360.0
REVIEW_FIX_CALL_TIMEOUT_SECONDS = 900.0
REVIEW_PARTIAL_STREAM_TIMEOUT_SECONDS = 45.0
REVIEW_FIX_HEARTBEAT_SECONDS = 15.0
REVIEW_AGENT_IDLE_TIMEOUT_SECONDS = 300.0
REVIEW_NATIVE_IMAGE_LIMIT = 8
REVIEW_FIX_ACTION_LIMIT = 4
REVIEW_FIX_TARGET_LIMIT = 3
MANAGED_REVIEW_ROUNDS_MAX = 4
NON_EMPIRICAL_EVIDENCE_MODES = frozenset({
    "design_only",
    "execution_pending",
    "planned",
})
BOUNDED_REVIEW_FALLBACK_EVIDENCE_MODES = frozenset({
    *NON_EMPIRICAL_EVIDENCE_MODES,
    "synthetic_preview",
})

AUDIT_BUNDLE_SCHEMA = 5
AUDIT_RUNTIME_SCHEMA = 1
AUDIT_REVIEWER_ROUTE_SCHEMA = 2
AUDIT_LAYER_SKILLS: dict[int, str] = {
    1: "experiment-audit",
    2: "result-to-claim",
    3: "paper-claim-audit",
    4: "citation-audit",
    5: "kill-argument",
    6: "proof-checker",
}
AUDIT_SCIENTIFIC_LAYERS = frozenset(range(1, 6))
AUDIT_REUSABLE_VERDICTS = frozenset({
    "PASS",
    "WARN",
    "NOT_APPLICABLE",
})


def _save_trace(project_path: str, skill_name: str, input_text: str, output_text: str) -> str:
    """Persist raw reviewer input/output for forensic replay."""
    from datetime import datetime
    import hashlib

    root = Path(project_path or ".")
    trace_root = root / ".merak" / "traces" / skill_name
    date = datetime.now().strftime("%Y%m%d")
    trace_root.mkdir(parents=True, exist_ok=True)
    trace_dir = trace_root / f"{date}_run_{time.time_ns()}_{uuid.uuid4().hex[:8]}"
    trace_dir.mkdir(parents=True, exist_ok=False)
    input_hash = hashlib.sha256(input_text.encode("utf-8", errors="ignore")).hexdigest()
    output_hash = hashlib.sha256(output_text.encode("utf-8", errors="ignore")).hexdigest()
    meta = {
        "skill": skill_name,
        "timestamp": time.time(),
        "input_sha256": input_hash,
        "output_sha256": output_hash,
        "input_length": len(input_text),
        "output_length": len(output_text),
    }
    atomic_write_json(trace_dir / "meta.json", meta)
    atomic_write_text(trace_dir / "input.txt", input_text)
    atomic_write_text(trace_dir / "output.txt", output_text)
    return str(trace_dir)


def _extract_json_object(text: str, required_key: str) -> dict[str, Any] | None:
    """Decode the first complete JSON object containing ``required_key``.

    Model responses may use Markdown fences and nested evidence objects. Regex
    matching cannot safely distinguish those braces, while ``raw_decode`` can.
    """
    decoder = json.JSONDecoder()
    for index, char in enumerate(text or ""):
        if char != "{":
            continue
        try:
            payload, _ = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict) and required_key in payload:
            return payload
    return None


def _source_bundle(
    root: Path,
    sources: list[Path],
) -> tuple[str, list[Path]]:
    unique = sorted(
        {
            path.resolve()
            for path in sources
            if path.is_file() and path.stat().st_size > 0
        },
        key=lambda path: path.as_posix(),
    )
    digest = hashlib.sha256()
    for path in unique:
        try:
            identity = path.relative_to(root).as_posix()
        except ValueError:
            identity = path.as_posix()
        digest.update(identity.encode("utf-8", errors="replace"))
        digest.update(b"::")
        digest.update(path.read_bytes())
        digest.update(b"\n")
    return digest.hexdigest(), unique


def review_source_bundle(project_path: str | Path) -> tuple[str, list[Path]]:
    root = Path(project_path).expanduser().resolve()
    from ..services.latex_bundle import latex_source_bundle

    _, paper_sources = latex_source_bundle(root / "paper")
    sources = [
        *paper_sources,
        root / "paper" / "TITLE.txt",
        root / "paper" / "CONTRIBUTION_BLUEPRINT.md",
        root / "paper" / "SCIENTIFIC_FREEZE.json",
        root / "paper" / "references.bib",
        root / "ideas" / "SELECTED_IDEA.json",
        root / "experiments" / "results" / "analysis.md",
        root / '.merak/quality/independent-matrix-audit.json',
        root / "experiments" / "METHOD_CONTRACT.json",
        root / "experiments" / "src" / "models.py",
        root / "experiments" / "src" / "objectives.py",
        root / "literature" / "SEARCH_EVIDENCE.json",
        root / "figures" / "SCIENTIFIC_ASSET_PLAN.json",
        root / "figures" / "FIGURE_MANIFEST.json",
        root / "NARRATIVE_REPORT.md",
        root / "experiments/results/simulated/reproducibility/replay/REPLAY_VERIFICATION.json",
        root / "experiments/results/simulated/reproducibility/replay/CONSTRUCTORS.md",
    ]
    return _source_bundle(root, sources)


_REVIEW_FIX_PATH_RE = re.compile(
    r"(?<![\w.-])"
    r"((?:paper|experiments|figures|literature|ideas|methods)"
    r"[\\/][A-Za-z0-9_.\\/-]+)",
    re.IGNORECASE,
)
_REVIEW_FIX_ALLOWED_SUFFIXES = frozenset({
    ".bib", ".json", ".md", ".py", ".tex", ".toml", ".yaml", ".yml",
})
_REVIEW_FIX_SECTION_ROUTES: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = (
    (
        (
            "dataset", "cohort", "sample", "population", "split", "endpoint",
            "statistic", "bootstrap", "baseline", "evaluation", "protocol",
            "数据集", "样本", "划分", "终点", "统计", "基线", "评估", "实验协议",
        ),
        ("paper/sections/04_experiments.tex", "paper/tables/study_design.tex"),
    ),
    (
        (
            "method", "implementation", "architecture", "objective", "loss",
            "decoder", "encoder", "formal", "algorithm",
            "方法", "实现", "架构", "目标函数", "损失", "形式化", "算法",
        ),
        ("paper/sections/03_method.tex",),
    ),
    (
        ("result", "finding", "analysis", "结果", "发现", "分析"),
        ("paper/sections/05_results.tex", "experiments/results/analysis.md"),
    ),
    (
        ("limitation", "threat", "ethic", "限制", "威胁", "伦理"),
        ("paper/sections/07_limitations.tex", "paper/sections/06_discussion.tex"),
    ),
    (
        ("citation", "reference", "bibliograph", "引用", "参考文献"),
        ("paper/references.bib",),
    ),
)


def _existing_review_fix_target(root: Path, raw_path: str) -> Path | None:
    """Resolve one model-suggested artifact without leaving the project."""
    cleaned = str(raw_path or "").strip().strip("`'\".,;:()[]{}，。；：（）")
    from ..services.paper_canonical_author_target import canonical_author_target
    cleaned = canonical_author_target(root, cleaned)
    if not cleaned:
        return None
    relative = Path(cleaned.replace("\\", "/"))
    candidates = [relative]
    if not relative.suffix:
        candidates.extend(relative.with_suffix(suffix) for suffix in (".tex", ".md", ".json"))
    for candidate in candidates:
        resolved = (root / candidate).resolve()
        try:
            resolved.relative_to(root)
        except ValueError:
            continue
        if (
            resolved.is_file()
            and resolved.suffix.casefold() in _REVIEW_FIX_ALLOWED_SUFFIXES
            and "review-stage" not in {
                part.casefold() for part in resolved.relative_to(root).parts
            }
        ):
            return resolved
    return None


def build_review_fix_scope(
    project_path: str | Path,
    paper_path: str | Path,
    review_round: ReviewRound,
) -> tuple[list[str], list[Path]]:
    """Turn broad review prose into a small, existing-file edit scope."""
    root = Path(project_path).expanduser().resolve()
    raw_actions = review_round.action_items or review_round.weaknesses
    from ..services.paper_canonical_author_target import canonical_author_feedback
    actions = [
        canonical_author_feedback(root, str(item).strip())[:1600]
        for item in raw_actions
        if str(item).strip()
    ][:REVIEW_FIX_ACTION_LIMIT]

    targets: list[Path] = []

    def add_target(raw: str) -> None:
        target = _existing_review_fix_target(root, raw)
        if target is not None and target not in targets:
            targets.append(target)

    for action in actions:
        explicit = [match.group(1) for match in _REVIEW_FIX_PATH_RE.finditer(action)]
        for raw in explicit:
            add_target(raw)
        if any(_existing_review_fix_target(root, raw) is not None for raw in explicit):
            continue
        folded = action.casefold()
        for keywords, routed_paths in _REVIEW_FIX_SECTION_ROUTES:
            if any(keyword in folded for keyword in keywords):
                for routed_path in routed_paths:
                    add_target(routed_path)

    if not targets:
        paper = Path(paper_path).expanduser()
        if not paper.is_absolute():
            paper = root / paper
        try:
            paper = paper.resolve()
            paper.relative_to(root)
        except ValueError:
            paper = root / "paper" / "main.tex"
        if paper.is_file():
            targets.append(paper)

    return actions, targets[:REVIEW_FIX_TARGET_LIMIT]


def audit_source_bundle(project_path: str | Path) -> tuple[str, list[Path]]:
    root = Path(project_path).expanduser().resolve()
    _, review_sources = review_source_bundle(root)
    from ..services.citation_source_evidence import current_citation_evidence
    sources = [
        *review_sources,
        *current_citation_evidence(root),
        # This is coordinator-generated reconciliation evidence.  It belongs to
        # the downstream audit bundle, but must not invalidate the independent
        # review merely because reconciliation refreshed its timestamp/content.
        root / "paper" / "CROSS_SECTION_REVIEW.md",
        root / "review-stage" / "REVIEW_STATE.json",
        root / "experiments" / "EXPERIMENT_PLAN.md",
        root / "experiments" / "METHOD_CONTRACT.json",
        root / "experiments" / "RUN_SPEC.json",
        root / "literature" / "references.bib",
        root / "literature" / "SEARCH_EVIDENCE.json",
    ]
    allowed = {
        ".csv", ".json", ".jsonl", ".log", ".md", ".npz", ".py", ".toml",
        ".tsv", ".txt", ".yaml", ".yml",
    }
    for artifact_root in (
        root / "experiments" / "src",
        root / "experiments" / "configs",
        root / "experiments" / "results",
        root / "experiments" / "logs",
        root / ".merak" / "experiments",
    ):
        if artifact_root.is_dir():
            sources.extend(
                path
                for path in artifact_root.rglob("*")
                if path.is_file()
                and path.suffix.casefold() in allowed
                and not any(
                    part in {"__pycache__", ".git", ".pytest_cache"}
                    for part in path.parts
                )
            )
    return _source_bundle(root, sources)


def _canonical_json_sha256(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def audit_runtime_attestation() -> dict[str, Any]:
    """Fingerprint every repository-owned component that can produce an audit."""

    from ..utils.runtime_source_root import server_source_root
    server_root = server_source_root()
    component_paths = {
        "workflows/review_audit.py": server_root / "workflows/review_audit.py",
        "agent/__init__.py": server_root / "agent" / "__init__.py",
        "agent/engine.py": server_root / "agent" / "engine.py",
        "services/api_visual_reviewer.py": (
            server_root / "services" / "api_visual_reviewer.py"
        ),
        "services/skill_orchestrator.py": (
            server_root / "services" / "skill_orchestrator.py"
        ),
        "services/skill_registry.py": (
            server_root / "services" / "skill_registry.py"
        ),
    }
    components: dict[str, str] = {}
    for name in ("audit_coordinator.py", "audit_layer_checkpoint.py", "audit_protocol.py", "audit_layers.py",
                 "audit_result_store.py", "audit_bundle_checks.py", "proof_audit_validation.py", "draft_delivery.py", "draft_review_evidence.py", "draft_audit_evidence.py", "audit_matrix_scope.py", "audit_policy_identity.py", "audit_provenance_facts.py", "audit_evidence_batches.py", "audit_batch_receipts.py", "audit_batch_checkpoint.py"):
        component_paths[f"workflows/{name}"] = server_root / "workflows" / name
    for name, path in component_paths.items():
        try:
            components[name] = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError:
            components[name] = "missing"
    payload: dict[str, Any] = {
        "schema": AUDIT_RUNTIME_SCHEMA,
        "components": components,
    }
    payload["signature"] = _canonical_json_sha256(payload)
    return payload


def audit_runtime_signature() -> str:
    return str(audit_runtime_attestation().get("signature") or "")


def audit_reviewer_route() -> dict[str, Any]:
    """Return the non-secret model/transport route that audit reuse depends on."""

    try:
        executor_provider, _executor, executor_identity = (
            model_router.get_provider_route(ModelRole.EXECUTOR)
        )
        executor_resolved = True
    except RuntimeError:
        executor_provider = str(
            getattr(model_router, "_strategy", {}).get(ModelRole.EXECUTOR)
            or "unconfigured"
        )
        executor_identity = f"unconfigured:{executor_provider}"
        executor_resolved = False
    try:
        reviewer_provider, _reviewer, reviewer_identity = (
            model_router.get_isolated_provider_route(
                ModelRole.REVIEWER,
            )
        )
        reviewer_resolved = True
    except RuntimeError:
        reviewer_provider = str(
            getattr(model_router, "_strategy", {}).get(ModelRole.REVIEWER)
            or "unconfigured"
        )
        reviewer_identity = f"unconfigured:{reviewer_provider}"
        reviewer_resolved = False
    return {
        "schema": AUDIT_REVIEWER_ROUTE_SCHEMA,
        "transport": "model-api",
        "executor": {
            "provider": str(executor_provider or ""),
            "model_identity": str(executor_identity or ""),
            "resolved": executor_resolved,
        },
        "reviewer": {
            "provider": str(reviewer_provider or ""),
            "model_identity": str(reviewer_identity or ""),
            "independent_of": "executor",
            "same_model_allowed": True,
            "same_model": str(reviewer_identity or "").casefold()
            == str(executor_identity or "").casefold(),
            "session_isolation": "fresh_context",
            "resolved": reviewer_resolved,
        },
    }


def audit_reviewer_route_sha256(route: dict[str, Any] | None = None) -> str:
    selected = route if isinstance(route, dict) else audit_reviewer_route()
    return _canonical_json_sha256(selected)


def audit_policy_sha256(skill_name: str) -> str:
    policy = AuditChain._full_policy(skill_name)
    from .audit_policy_identity import canonical_policy_digest
    from ..services.skill_orchestrator import skill_orchestrator
    metadata = skill_orchestrator.registry.get_skill(skill_name.lstrip('/'))
    return canonical_policy_digest(policy, str(metadata.file_path) if metadata else "")


def proof_source_bundle(
    project_path: str | Path,
) -> tuple[str, dict[str, str], list[Path], int, list[str]]:
    from .audit_bundle_validation import proof_source_bundle as validate_sources

    return validate_sources(project_path)


def proof_semantic_sha256(
    proof_source_bundle_sha256: str, proof: dict[str, Any],
) -> str:
    from .audit_bundle_validation import proof_semantic_sha256 as semantic_hash

    return semantic_hash(proof_source_bundle_sha256, proof)


def validate_proof_audit_artifact(
    project_path: str | Path, **kwargs: Any,
) -> tuple[list[str], dict[str, Any]]:
    from .audit_bundle_validation import validate_proof_audit_artifact as validate

    return validate(project_path, **kwargs)


def validate_audit_bundle(
    project_path: str | Path, **kwargs: Any,
) -> dict[str, Any]:
    from .audit_bundle_validation import validate_audit_bundle as validate

    return validate(project_path, **kwargs)
class CrossModelReviewer(ReviewProtocolMixin, ReviewVisualsMixin):
    """跨模型审稿引擎"""

    async def run_review_loop(
        self, paper_path: str, project_path: str, max_rounds: int = 4,
        difficulty: str = "medium", on_progress: Optional[callable] = None,
        run_id: str = "", researcher_feedback: str = "",
        evidence_mode: str = "executed", transport_retry: Optional[callable] = None,
    ) -> ReviewState:
        from .review_loop import ReviewContext, run_review_loop

        return await run_review_loop(ReviewContext(
            reviewer=self, paper_path=paper_path, project_path=project_path,
            max_rounds=max_rounds, difficulty=difficulty,
            on_progress=on_progress, run_id=run_id,
            researcher_feedback=researcher_feedback,
            evidence_mode=evidence_mode, transport_retry=transport_retry,
        ))
    @staticmethod
    def _load_state(
        project_path: str, *, run_id: str, max_rounds: int,
        evidence_mode: str,
    ) -> Optional[ReviewState]:
        from .review_state_store import load_review_state

        return load_review_state(
            project_path, run_id=run_id, max_rounds=max_rounds,
            evidence_mode=evidence_mode,
        )
    def _save_state(self, state: ReviewState, project_path: str) -> None:
        from .review_state_store import save_review_state

        save_review_state(
            state, project_path, source_bundle=review_source_bundle
        )


class AuditChain(AuditLayersMixin, AuditProtocolMixin):
    """5层审计链"""

    _INVENTORY_SUFFIXES = {
        ".bib",
        ".csv",
        ".json",
        ".jsonl",
        ".log",
        ".md",
        ".py",
        ".tex",
        ".toml",
        ".tsv",
        ".yaml",
        ".yml",
    }

    async def run_full_audit(
        self, paper_path: str, experiment_dir: str, project_path: str,
        on_progress: Optional[callable] = None,
        evidence_mode: str = "executed", layer_timeout_seconds: int = 420,
        run_id: str = "",
    ) -> list[AuditResult]:
        from .audit_coordinator import AuditContext, run_full_audit

        return await run_full_audit(AuditContext(
            chain=self, paper_path=paper_path, experiment_dir=experiment_dir,
            project_path=project_path, on_progress=on_progress,
            evidence_mode=evidence_mode,
            layer_timeout_seconds=layer_timeout_seconds, run_id=run_id,
        ))
    @classmethod
    def _proof_detector_result(cls, project_path: str) -> AuditResult | None:
        from .audit_deterministic import proof_detector_result

        return proof_detector_result(
            project_path, policy_loaded=cls._policy_loaded
        )
    @staticmethod
    def _deterministic_fallback(
        layer_num: int, layer_name: str, project_path: str, error: Exception, *,
        evidence_mode: str = "design_only",
    ) -> AuditResult:
        from .audit_deterministic import deterministic_fallback

        return deterministic_fallback(
            layer_num, layer_name, project_path, error,
            evidence_mode=evidence_mode,
        )


# 全局实例
cross_model_reviewer = CrossModelReviewer()
audit_chain = AuditChain()
