"""Audit input inventory, skill policy, reviewer invocation, and reuse."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from .review_models import AuditResult, Verdict

_INVENTORY_SUFFIXES = {
    ".bib", ".csv", ".json", ".jsonl", ".log", ".md", ".py", ".tex",
    ".toml", ".tsv", ".yaml", ".yml",
}


class AuditProtocolMixin:
    @classmethod
    def _verified_file_inventory(
        cls, project_path: str, paper_path: str, experiment_dir: str, *,
        limit: int = 160,
    ) -> str:
        root = Path(project_path).resolve()
        candidates = [
            path.resolve() for path in (
                Path(paper_path), root / "paper" / "references.bib",
                root / "literature" / "references.bib",
                root / "ideas" / "SELECTED_IDEA.json",
                root / "NARRATIVE_REPORT.md",
                root / "figures" / "FIGURE_MANIFEST.json",
                root / "review-stage" / "REVIEW_STATE.json",
            ) if path.is_file()
        ]
        experiment_root = Path(experiment_dir)
        if experiment_root.is_dir():
            for path in sorted(experiment_root.rglob("*")):
                if (
                    not path.is_file() or path.suffix.casefold() not in _INVENTORY_SUFFIXES
                    or any(part in {"__pycache__", ".git", ".pytest_cache"} for part in path.parts)
                ):
                    continue
                candidates.append(path.resolve())
                if len(candidates) >= limit:
                    break
        unique = list(dict.fromkeys(candidates))[:limit]
        return "\n".join(f"- {path}" for path in unique) if unique else (
            "- (no verified audit input files were found)"
        )

    @classmethod
    def _read_protocol(
        cls, project_path: str, paper_path: str, experiment_dir: str
    ) -> str:
        inventory = cls._verified_file_inventory(
            project_path, paper_path, experiment_dir
        )
        return f"""

Verified existing files for this audit:
{inventory}

Read protocol:
- Read only an exact path listed above.
- If another file is needed, use Glob first and Read only a path returned by Glob.
- Never guess shortened paths or move a file from experiments/results into experiments/.
- Report a missing evidence category once; do not probe expected aliases with repeated failed Read calls.
""".rstrip()

    @staticmethod
    def _full_policy(skill_name: str) -> str:
        from ..services.skill_orchestrator import skill_orchestrator

        policy = skill_orchestrator.full_policy(skill_name)
        if policy:
            return policy
        from os import environ

        skills_root = Path(
            environ.get("MERAK_SKILLS_PATH") or Path(__file__).parents[2] / "merak-skills"
        )
        if skills_root.is_dir():
            skill_orchestrator.registry.scan_directory(skills_root)
            policy = skill_orchestrator.full_policy(skill_name)
        return policy

    @classmethod
    def _policy_loaded(cls, skill_name: str) -> bool:
        return bool(cls._full_policy(skill_name))

    @classmethod
    def _system_prompt(cls, skill_name: str, task_prompt: str) -> str:
        policy = cls._full_policy(skill_name)
        if not policy:
            return task_prompt
        return (
            task_prompt + f"\n\n## Loaded independent MERAK skill: /{skill_name}\n"
            "This complete SKILL.md is the executable contract for this isolated "
            "reviewer session. Perform the audit; do not summarize the skill.\n\n"
            + policy
        )

    async def _invoke_audit_reviewer(
        self, *, project_path: str, skill_name: str, system_prompt: str,
        audit_input: str, on_event: Optional[Any],
    ) -> tuple[str, str, str, str]:
        from ..services.api_visual_reviewer import api_visual_reviewer
        from .review_audit import REVIEW_MODEL_CALL_TIMEOUT_SECONDS, audit_source_bundle

        source_hash, source_paths = audit_source_bundle(project_path)
        from datetime import datetime, timezone
        system_prompt += f"\nCurrent UTC date: {datetime.now(timezone.utc).date().isoformat()}; use this date when judging publication chronology.\n"
        from .audit_provenance_facts import provenance_context
        system_prompt += provenance_context(Path(project_path), skill_name)
        schema = _audit_schema(skill_name)
        from .draft_delivery import AUDIT_DELIVERY, DRAFT, DRAFT_POLICY, draft_schema
        if AUDIT_DELIVERY.get() == DRAFT:
            schema = draft_schema(schema)
            system_prompt += "\n\n" + DRAFT_POLICY
            from .draft_audit_evidence import draft_audit_evidence
            source_hash, source_paths, coverage = draft_audit_evidence(Path(project_path), source_paths, skill_name, allow_partition=True)
            system_prompt += coverage

        async def activity() -> None:
            if on_event is not None:
                await on_event(None)

        if AUDIT_DELIVERY.get() == DRAFT:
            from .audit_evidence_batches import invoke_batched_audit
            result = await invoke_batched_audit(reviewer=api_visual_reviewer, project_path=project_path,
                skill=skill_name, prompt=system_prompt + "\n\n## Reviewer task\n" + audit_input,
                schema=schema, paths=source_paths, source_hash=source_hash,
                timeout=REVIEW_MODEL_CALL_TIMEOUT_SECONDS, activity=activity)
            return result.text, result.invocation_id, result.model_identity, result.trace_path
        result = await api_visual_reviewer.invoke(
            project_path=project_path,
            prompt=system_prompt + "\n\n## Reviewer task\n" + audit_input,
            purpose=f"audit-{skill_name}", schema=schema,
            evidence_paths=source_paths, evidence_bundle_sha256=source_hash,
            timeout_seconds=REVIEW_MODEL_CALL_TIMEOUT_SECONDS,
            on_activity=activity,
        )
        return result.text, result.invocation_id, result.model_identity, result.trace_path

    @staticmethod
    def _evidence_mode_policy(evidence_mode: str) -> str:
        if evidence_mode in {"executed", "existing_results", "secondary_analysis"}:
            return (
                f"Evidence mode is {evidence_mode}. Require provenance-backed result "
                "artifacts, metrics, uncertainty, and claim-to-result consistency."
            )
        if evidence_mode == "synthetic_preview":
            return _SIMULATION_AUDIT_POLICY
        return _PLANNED_AUDIT_POLICY.format(evidence_mode=evidence_mode)

    @staticmethod
    def _load_reusable_model_results(
        project_path: str, *, run_id: str, evidence_mode: str
    ) -> dict[int, AuditResult]:
        if not run_id:
            return {}
        from .review_audit import validate_audit_bundle

        validation = validate_audit_bundle(
            Path(project_path).expanduser().resolve(), run_id=run_id,
            evidence_mode=evidence_mode, allow_non_model_layers=True,
        )
        if validation.get("valid") is not True:
            return {}
        reusable = _reusable_scientific_results(
            validation.get("entries"), evidence_mode
        )
        proof = _reusable_proof_result(validation.get("proof_payload"))
        if proof is not None:
            reusable[6] = proof
        return reusable


def _audit_schema(skill_name: str) -> dict[str, Any]:
    schema: dict[str, Any] = {
        "type": "object", "required": ["verdict", "summary"],
        "properties": {
            "verdict": {"type": "string", "enum": [
                "PASS", "WARN", "FAIL", "NOT_APPLICABLE", "BLOCKED", "ERROR",
            ]},
            "summary": {"type": "string", "minLength": 1},
            "evidence": {"type": "array"}, "kill_memo": {"type": "string"},
            "adjudication": {"type": "string"}, "audit_skill": {"type": "string"},
            "reason_code": {"type": "string"}, "details": {"type": "object"},
        },
        "additionalProperties": True,
    }
    if skill_name == "proof-checker":
        schema["required"] = [
            "audit_skill", "verdict", "reason_code", "summary", "details", "evidence",
        ]
        schema["properties"]["audit_skill"] = {
            "type": "string", "const": "proof-checker",
        }
    return schema


def _reusable_scientific_results(
    entries: Any, evidence_mode: str
) -> dict[int, AuditResult]:
    from .review_audit import AUDIT_LAYER_SKILLS

    reusable = {}
    for item in entries if isinstance(entries, list) else []:
        if not _valid_reusable_entry(item, evidence_mode):
            continue
        try:
            layer = int(item.get("layer") or 0)
            verdict = Verdict(str(item.get("verdict") or "ERROR").upper())
        except (TypeError, ValueError):
            continue
        if (
            layer not in range(1, 6)
            or verdict not in {Verdict.PASS, Verdict.WARN, Verdict.NOT_APPLICABLE, Verdict.FAIL, Verdict.BLOCKED}
            or str(item.get("skill_name") or "") != AUDIT_LAYER_SKILLS[layer]
            or not str(item.get("summary") or "").strip()
        ):
            continue
        reusable[layer] = AuditResult(
            layer=layer, layer_name=str(item.get("layer_name") or ""),
            verdict=verdict, summary=str(item.get("summary") or ""),
            details=str(item.get("details") or ""),
            evidence=list(item.get("evidence") or []), method="model",
            skill_name=str(item.get("skill_name") or ""),
            session_id=str(item.get("session_id") or ""), policy_loaded=True,
            model_name=str(item.get("model_name") or ""),
            trace_path=str(item.get("trace_path") or ""),
            delivery_goal=str(item.get("delivery_goal") or "submission_candidate"),
            draft_blockers=item.get("draft_blockers"),
        )
    return reusable


def _valid_reusable_entry(item: Any, evidence_mode: str) -> bool:
    return bool(
        isinstance(item, dict) and item.get("method") == "model"
        and item.get("managed_by") == "merak_audit_chain"
        and item.get("policy_loaded") is True
        and str(item.get("session_id") or "").strip()
        and str(item.get("model_name") or "").strip()
        and str(item.get("evidence_mode") or "") == evidence_mode
    )


def _reusable_proof_result(payload: Any) -> AuditResult | None:
    proof = payload if isinstance(payload, dict) else {}
    if not proof:
        return None
    try:
        verdict = Verdict(str(proof.get("verdict") or "ERROR").upper())
    except (ValueError, AttributeError):
        return None
    method = str(proof.get("method") or "")
    if (
        verdict not in {Verdict.PASS, Verdict.WARN, Verdict.NOT_APPLICABLE}
        or method not in {"model", "deterministic_detector"}
    ):
        return None
    return AuditResult(
        layer=6, layer_name="Proof Checker", verdict=verdict,
        summary=str(proof.get("summary") or ""),
        details=proof.get("details") or {}, evidence=list(proof.get("evidence") or []),
        method=method, skill_name="proof-checker",
        session_id=str(proof.get("session_id") or ""),
        policy_loaded=proof.get("policy_loaded") is True,
        model_name=str(proof.get("reviewer_model") or proof.get("model_name") or ""),
        reason_code=str(proof.get("reason_code") or ""),
        audited_input_hashes=dict(proof.get("audited_input_hashes") or {}),
        trace_path=str(proof.get("trace_path") or ""),
    )


_SIMULATION_AUDIT_POLICY = """Evidence mode is a selected fixed benchmark study.
Require reproducible generator/seed/scenario provenance and complete quantitative analysis within
the defined benchmark. Titles, abstracts, scientific sections, figures, tables, and captions use
ordinary scientific prose. Methods must explain the actual simulation generator, synthetic inputs,
fixed configurations and statistical construction. Machine paths and run IDs remain in sidecars.
Require exactly one canonical Simulation Study Disclosure after the Conclusion and before the
bibliography; this paragraph does not replace the reproducible scientific Methods account. Do not add warning banners, preview labels,
watermarks, or caption caveats. FAIL if benchmark findings are represented as measurements
from physical, clinical, field, or production systems without independent provenance. Submission
eligibility remains sidecar state and must not appear in visible manuscript content.

Binding adjudication rules for this selected simulation study:
- The deterministic generator is the authorized execution mechanism for this evidence mode. Do
  not call its outputs phantom results and do not FAIL merely because no physical training,
  acquisition, field deployment, clinical collection, or hardware measurement was performed.
- Distinguish the generator seed from the registered replicate seeds. An aggregate row may carry
  the generator seed in simulation_seed/source_run_id and the complete replicate identities and
  values in seed/seed_values; that representation is valid when the manifest defines both roles.
- Audit internal reproducibility, mathematical consistency, registered comparisons, uncertainty,
  claim alignment, and the single end-of-paper disclosure. External validity beyond the selected
  scenario is a limitation or WARN, not evidence fabrication.
- A completed negative or non-decisive registered result is scientifically complete when its
  decision fields and limitations are present and the manuscript narrows the claim accordingly.
  Never require an author or repair agent to manufacture a favorable reversal, p-value, effect,
  ablation, or superiority result in order to pass.
- FAIL only for an actual contradiction, untraceable value, invalid calculation, omitted required
  result family, undisclosed physical-world interpretation, or unsupported manuscript claim that
  remains after applying the simulation-study scope above."""

_PLANNED_AUDIT_POLICY = """Evidence mode is {evidence_mode} because experiment execution is disabled.
Judge whether the pre-experiment record is honest, executable, falsifiable, and traceable.
- Missing empirical metrics alone is NOT a failure; use NOT_APPLICABLE or WARN.
- FAIL if the paper invents values, treats templates/dry-runs as evidence, or makes unsupported claims.
- Do not ask an editing agent to manufacture experiments."""
