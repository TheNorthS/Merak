"""Coordinate stage-owned implementation builds and their persisted hash records.

A completed stage requires current interface and reachability checks, not merely
new timestamps or an author assertion. This service does not run experiments."""

from __future__ import annotations

import hashlib
import time
from pathlib import Path
from typing import Any

from ..utils.atomic_write import atomic_write_json


from .implementation_stages import (
    COMPUTATIONAL_STAGES,
    FORMAL_STAGES,
    ML_STAGES,
    PROTOCOL_STAGES,
    ImplementationStage,
)
from .implementation_stage_validation import target_paths, validate_stage
from .implementation_blueprint import ensure_blueprint
from .implementation_build_revalidation import revalidate_existing_build
from .implementation_state_io import load_implementation_state
from .implementation_dependencies import stage_semantic_inputs, stage_input_fingerprint
from .implementation_build_findings import implementation_findings, implementation_repair_scope
from .experiment_output_contract import output_provenance_instruction

_state_json = load_implementation_state


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _path_hash(path: Path) -> str:
    try:
        return _sha256_bytes(path.read_bytes()) if path.is_file() else "missing"
    except OSError:
        return "unreadable"


class ExperimentImplementationBuildService:
    """Drive resumable, gate-separated implementation instead of one-shot codegen."""

    blueprint_relative_path = Path("experiments") / "IMPLEMENTATION_BLUEPRINT.json"
    build_relative_path = Path("experiments") / "IMPLEMENTATION_BUILD.json"

    def blueprint_path(self, project_path: str | Path) -> Path:
        return Path(project_path).expanduser().resolve() / self.blueprint_relative_path

    def build_path(self, project_path: str | Path) -> Path:
        return Path(project_path).expanduser().resolve() / self.build_relative_path

    @staticmethod
    def _selected_contract(root: Path) -> dict[str, Any]:
        return _state_json(root / "ideas" / "SELECTED_IDEA.json")

    @staticmethod
    def _method_contract(root: Path) -> dict[str, Any]:
        return _state_json(root / "experiments" / "METHOD_CONTRACT.json")

    @staticmethod
    def _run_spec(root: Path) -> dict[str, Any]:
        return _state_json(root / "experiments" / "RUN_SPEC.json")

    @staticmethod
    def _stages_for_family(family: str) -> tuple[ImplementationStage, ...]:
        return {
            "machine_learning": ML_STAGES,
            "computational_general": COMPUTATIONAL_STAGES,
            "external_protocol": PROTOCOL_STAGES,
            "formal_verification": FORMAL_STAGES,
        }.get(str(family or "").strip().casefold(), COMPUTATIONAL_STAGES)

    def ensure_blueprint(
        self,
        project_path: str | Path,
        direction: str = "",
    ) -> dict[str, Any]:
        return ensure_blueprint(self, project_path, direction)

    def project_stages(self, project_path: str | Path, family: str) -> tuple[ImplementationStage, ...]:
        from .impl_stage_targets import project_stages
        return project_stages(project_path, family, self._stages_for_family(family))

    def project_stage_by_id(self, project_path: str | Path, stage_id: str, family: str) -> ImplementationStage:
        for stage in self.project_stages(project_path, family):
            if stage.id == stage_id:
                return stage
        raise ValueError(f"Unknown implementation stage: {stage_id}")

    @classmethod
    def _stage_by_id(
        cls,
        stage_id: str,
        family: str = "machine_learning",
    ) -> ImplementationStage:
        for stage in cls._stages_for_family(family):
            if stage.id == stage_id:
                return stage
        raise ValueError(f"Unknown implementation stage: {stage_id}")

    @staticmethod
    def _family(blueprint: dict[str, Any]) -> str:
        return str(
            blueprint.get("implementation_family") or "computational_general"
        ).strip().casefold()

    def applicable(self, project_path: str | Path, direction: str = "") -> bool:
        # Every research family gets a contract pass.  Protocol and formal
        # projects use the same resumable ownership machinery, but their stage
        # validators below check protocol/proof semantics instead of ML
        # training operations.
        self.ensure_blueprint(project_path, direction)
        return True

    def stages(
        self,
        project_path: str | Path,
        direction: str = "",
    ) -> tuple[ImplementationStage, ...]:
        blueprint = self.ensure_blueprint(project_path, direction)
        return self.project_stages(project_path, self._family(blueprint))

    _target_paths = staticmethod(target_paths)

    def validate_stage(
        self,
        project_path: str | Path,
        stage_id: str,
        direction: str = "",
    ) -> dict[str, Any]:
        return validate_stage(self, project_path, stage_id, direction)

    def output_hash(self, project_path: str | Path, stage_id: str) -> str:
        root = Path(project_path).expanduser().resolve()
        blueprint = self.ensure_blueprint(root)
        stage = self.project_stage_by_id(root, stage_id, self._family(blueprint))
        digest = hashlib.sha256()
        for path in self._target_paths(root, stage):
            digest.update(path.relative_to(root).as_posix().encode("utf-8"))
            digest.update(_path_hash(path).encode("ascii"))
        return digest.hexdigest()

    def input_hash(
        self,
        project_path: str | Path,
        stage_id: str,
        direction: str = "",
    ) -> str:
        root = Path(project_path).expanduser().resolve()
        digest = hashlib.sha256(b"implementation-training-input-v3" if stage_id == "training" else b"implementation-input-v2")
        for path in stage_semantic_inputs(root, stage_id):
            digest.update(path.relative_to(root).as_posix().encode("utf-8"))
            digest.update(stage_input_fingerprint(path, stage_id=stage_id).encode("ascii"))
        blueprint = self.ensure_blueprint(root, direction)
        for stage in self.project_stages(root, self._family(blueprint)):
            if stage.id == stage_id:
                break
            digest.update(self.output_hash(root, stage.id).encode("ascii"))
        digest.update(direction.encode("utf-8", errors="replace"))
        return digest.hexdigest()

    def load_build(self, project_path: str | Path) -> dict[str, Any]:
        return _state_json(self.build_path(project_path))

    def can_reuse(
        self,
        project_path: str | Path,
        stage_id: str,
        direction: str = "",
    ) -> bool:
        build = self.load_build(project_path)
        record = (build.get("stages") or {}).get(stage_id)
        if not isinstance(record, dict) or record.get("status") != "accepted":
            return False
        return bool(
            record.get("input_sha256") == self.input_hash(project_path, stage_id, direction)
            and record.get("output_sha256") == self.output_hash(project_path, stage_id)
            and self.validate_stage(project_path, stage_id, direction).get("passed")
        )

    def record_stage(
        self,
        project_path: str | Path,
        stage_id: str,
        report: dict[str, Any],
        direction: str = "",
        *,
        attempts: int = 1,
        session_summaries: list[str] | None = None,
        handled_obligations_sha256: str = "",
    ) -> dict[str, Any]:
        root = Path(project_path).expanduser().resolve()
        path = self.build_path(root)
        build = self.load_build(root)
        if not build:
            build = {
                "schema": 1,
                "mode": "staged_implementation",
                "stage_order": [
                    stage.id
                    for stage in self.project_stages(
                        root, self._family(self.ensure_blueprint(root, direction))
                    )
                ],
                "stages": {},
            }
        build.setdefault("stages", {})[stage_id] = {
            "status": "accepted" if report.get("passed") else "needs_revision",
            "attempts": attempts,
            "input_sha256": self.input_hash(root, stage_id, direction),
            "output_sha256": self.output_hash(root, stage_id),
            "targets": list(report.get("targets") or []),
            "issues": list(report.get("issues") or []),
            "updated_at": time.time(),
            "session_summaries": list(session_summaries or [])[-2:],
            "handled_obligations_sha256": handled_obligations_sha256 if report.get("passed") else "",
        }
        accepted: list[str] = []
        blueprint = self.ensure_blueprint(root, direction)
        stages = self.project_stages(root, self._family(blueprint))
        for candidate in stages:
            candidate_record = build["stages"].get(candidate.id) or {}
            if candidate_record.get("status") != "accepted":
                continue
            if (
                candidate_record.get("input_sha256")
                != self.input_hash(root, candidate.id, direction)
                or candidate_record.get("output_sha256")
                != self.output_hash(root, candidate.id)
            ):
                continue
            accepted.append(candidate.id)
        build["status"] = (
            "complete" if len(accepted) == len(stages) else "in_progress"
        )
        build["accepted_stages"] = accepted
        build["current_stage"] = next(
            (stage.id for stage in stages if stage.id not in accepted),
            "",
        )
        build["updated_at"] = time.time()
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(path, build)
        return build

    def revalidate_existing_build(
        self,
        project_path: str | Path,
        direction: str = "",
    ) -> dict[str, Any]:
        return revalidate_existing_build(self, project_path, direction)

    def audit(
        self,
        project_path: str | Path,
        direction: str = "",
    ) -> dict[str, Any]:
        blueprint = self.ensure_blueprint(project_path, direction)
        stages = self.project_stages(project_path, self._family(blueprint))
        reports = [
            self.validate_stage(project_path, stage.id, direction)
            for stage in stages
        ]
        issues = [
            f"{report['stage_id']}: {issue}"
            for report in reports
            for issue in report.get("issues", [])
        ]
        build = self.load_build(project_path)
        stage_records = build.get("stages") if isinstance(build, dict) else {}
        stage_records = stage_records if isinstance(stage_records, dict) else {}
        for stage in stages:
            record = stage_records.get(stage.id)
            if not isinstance(record, dict):
                issues.append(
                    f"{stage.id}: staged implementation acceptance record is missing"
                )
                continue
            if record.get("status") != "accepted":
                recorded_issues = "; ".join(
                    str(item) for item in record.get("issues", [])[:4]
                )
                issues.append(
                    f"{stage.id}: staged implementation record is not accepted"
                    + (f" ({recorded_issues})" if recorded_issues else "")
                )
                continue
            if (
                record.get("input_sha256")
                != self.input_hash(project_path, stage.id, direction)
                or record.get("output_sha256")
                != self.output_hash(project_path, stage.id)
            ):
                issues.append(
                    f"{stage.id}: accepted stage fingerprint is stale"
                )
        issues = list(dict.fromkeys(issues))
        findings = implementation_findings(reports, issues)
        return {
            "applicable": True,
            "blocking": bool(issues),
            "status": "blocked" if issues else "complete",
            "stages": reports,
            "issues": issues,
            "findings": findings,
            "repair_scope": implementation_repair_scope(findings),
            "blueprint_path": str(self.blueprint_path(project_path)),
            "build_path": str(self.build_path(project_path)),
        }

    def stage_prompt(
        self,
        project_path: str | Path,
        stage_id: str,
        direction: str,
        findings: list[str] | None = None,
        owned_targets: list[str] | None = None,
    ) -> str:
        root = Path(project_path).expanduser().resolve()
        from .impl_stage_targets import existing_stage_review_instruction
        review_instruction = existing_stage_review_instruction(root, stage_id, self.validate_stage(root, stage_id, direction), findings)
        blueprint = self.ensure_blueprint(root, direction)
        family = self._family(blueprint)
        stages = self.project_stages(root, family)
        stage = self.project_stage_by_id(root, stage_id, family)
        domain_contract = blueprint.get("domain_evidence_contract") or {}
        mechanisms = [f"{item.get('id')}: {item.get('name')}" for item in blueprint.get("mechanisms") or [] if isinstance(item, dict)]
        effective_targets = list(dict.fromkeys(owned_targets or stage.targets))
        effective_target_set = set(effective_targets)
        prior_targets = []
        for candidate in stages:
            if candidate.id == stage_id:
                break
            prior_targets.extend(
                target for target in candidate.targets
                if target not in effective_target_set
            )
        issue_text = "\n".join(f"- {item}" for item in findings or []) or "- none; perform the complete stage"
        return f"""Implement exactly one stage of the experiment codebase.

Stage: {stage.id} — {stage.title}
Purpose: {stage.purpose}
Research direction: {direction}
Implementation family: {family}
Publication family: {blueprint.get('research_family') or 'generic_quantitative'}
Study archetype: {blueprint.get('study_archetype') or 'generic_empirical'}
Frozen blueprint: experiments/IMPLEMENTATION_BLUEPRINT.json
Frozen idea: ideas/SELECTED_IDEA.json
Experiment plan: experiments/EXPERIMENT_PLAN.md

Required accepted mechanisms:
{chr(10).join('- ' + item for item in mechanisms) or '- read the frozen idea contract'}

Domain evidence contract (adapt implementation to these requirements):
- Analysis unit: {domain_contract.get('analysis_unit') or 'declare the independent analysis unit'}
- Uncertainty: {domain_contract.get('uncertainty') or 'match uncertainty to the study design'}
- Statistics: {', '.join(str(item) for item in domain_contract.get('statistics') or []) or 'declare estimands and uncertainty'}
- Provenance: {', '.join(str(item) for item in domain_contract.get('provenance') or []) or 'bind outputs to data/config/run identity'}

Current validation and independent-review findings:
{issue_text}
Current review-or-repair operation: {review_instruction + chr(10) + output_provenance_instruction()}

Files owned by this stage:
{chr(10).join('- ' + item for item in effective_targets)}

Read-only upstream implementation inputs:
{chr(10).join('- ' + item for item in prior_targets) or '- frozen research/design contracts only'}

Rules:
1. Read the complete blueprint, idea, plan, method contract, run spec, config, and existing upstream source before editing.
2. Implement substantive project-specific code in this stage's owned files. Do not emit a scaffold, TODO, placeholder, static-only validator, or fake result.
3. Preserve stable claim/mechanism IDs and the scientific method. Do not simplify the accepted idea to make coding easier.
4. You may import and call upstream modules. Do not rewrite files owned by earlier stages unless they are explicitly listed above as cross-stage repair targets selected from deterministic findings.
5. Do not run training or invent results. Static source authoring and bounded test definitions are allowed.
6. Integration provides evidence for mechanisms reachable from RUN_SPEC.entrypoint. Only the runtime may finalize METHOD_CONTRACT.status=implemented after complete deterministic validation; no model may edit its lifecycle state.
7. Implement or repair invalid/missing files, then re-read them and report exactly what changed. If the current review-or-repair operation permits review of a fresh valid implementation, preserve its correct bytes and report the actual checks instead; the runtime still requires this real invocation and a fresh passing gate.
8. Keep implementation readiness separate from execution evidence: after integration, METHOD_CONTRACT may be implemented and RUN_SPEC must expose the real scientific command/execution mode, while execution_status may remain not_executed and execution_prohibited_in_this_stage may remain true. Never describe a completed runnable implementation itself as scaffold_only or planned_code_check_only.
9. Existing METHOD_CONTRACT checks are read-only and keep `id` and `description`. In the integration evidence patch, use `symbols` only for real module/class/function/method definitions, `data_keys` for exact batch/dictionary/output keys, `anchors` for executable source fragments, and `config_keys` for dotted structured-config paths. Never label a local variable or dictionary key as a symbol or use an `evidence_register_ref`-only placeholder.
10. The declared entrypoint must expose a reachable `main()` or `run()` path and call every declared runtime evidence symbol, including final evaluation and result persistence. Symbols are module-qualified obligations, not alternatives: one reachable helper cannot satisfy a check containing other disconnected functions. Keep supporting preflight/tests distinct. Variable names such as checkpoint_state or metric_name cannot prove an IO or evaluation operation.
11. For stochastic studies, write the frozen integer execution seed list in RUN_SPEC top-level `seeds` and use the same values in the runner configuration; do not invent new seeds or substitute an augmentation/sampler seed. Deterministic families must declare their actual family instead of fake repetitions.
11. METHOD_CONTRACT lifecycle status is runtime-owned and read-only. Preserve its current state. Integration sets RUN_SPEC implementation readiness independently of `execution_status=not_executed`, which records that training has not run; never downgrade completed code merely because empirical execution is pending.
12. RUN_SPEC's formal scientific command must be directly executable. Do not leave angle-bracket placeholders such as `<manifest_selected_ids>` or arbitrary `{{field}}` templates. Read frozen IDs from a project-local manifest/config, or use scheduler-owned `{{seed}}`, `{{batch_size}}`, `{{work_dir}}`, `{{condition}}`, `{{axis}}`, and `{{output_dir}}` fields. Machine-learning and stochastic computational studies must declare valid repeat seeds; deterministic formal-verification/external-protocol studies must declare their deterministic family instead of inventing stochastic seeds.
13. Every `claim_evidence_plan` item must use the canonical keys `idea_claim_id`, non-empty `outcomes`, and non-empty `failure_conditions`. Explanatory aliases such as `observation`, `endpoint_and_decision`, or `alternative_explanations` may be retained, but they do not replace the canonical fields.
14. Reparse every edited JSON/YAML file before finishing. YAML mappings must use `key: value`; quote scalar text containing a colon and never place an indented child mapping beneath a bare scalar line.
15. METHOD_CONTRACT uses only current schema=2. Preserve its authored `scientific_scene` objects, relations, public labels, and provenance while adding implementation evidence; integration must never replace the design contract with a code-only subset.
16. The integration model must write `experiments/IMPLEMENTATION_EVIDENCE_PATCH.json` schema 1 with a non-empty `checks` list. Each check uses `check_id`, `description`, `idea_mechanism_ids` (the exact frozen mechanism IDs this check implements, or [] for an integration-only check), and evidence objects containing project-local `path` plus typed `symbols`, `data_keys`, `anchors`, or `config_keys`. Explicitly cover every required frozen mechanism; check names never imply a mapping. Do not edit METHOD_CONTRACT; the runtime merges evidence and the explicit mechanism-to-check links, validates the full reachable path, and finalizes lifecycle state.
17. RUN_SPEC.implementation_stage_targets is runtime-owned read-only metadata. Preserve it byte-for-value; only runtime configuration may change stage ownership. Existing package targets are canonical: never create retired flat aliases or substitute files outside this exact inventory.
18. The current instruction not to execute research is an authoring-session boundary, not a reason to make the generated scientific entrypoint permanently reject execution. The platform owns execution authorization. If the entrypoint requires an explicit execution flag, include it in RUN_SPEC's formal scientific command and preserve a separate preflight command; input/data preconditions must still fail clearly. Never require an undocumented flag or an unregistered config rewrite to run the declared command.
"""


experiment_implementation_build_service = ExperimentImplementationBuildService()
