"""Bounded, resumable orchestration for staged manuscript authoring."""

from __future__ import annotations

import asyncio
import re
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

from .manuscript_text import read_owned_state, sha256, write_json
from .paper_revision_queue import queue_consistency_authors
from .paper_canonical_author_target import canonical_author_feedback
from .paper_stage_cache_revalidation import (
    AUTOMATIC_CONSISTENCY_DIRECTIVE, automatic_consistency_revalidation,
    bound_stage_content, global_artifact_issue, stage_freshness_only,
)

StageInvoker = Callable[[str, str, str], Awaitable[str]]
EventEmitter = Callable[[str, dict[str, Any]], Awaitable[None]]


@dataclass
class StageRun:
    stage_id: str
    record: dict[str, Any]
    revision_issues: list[str]
    prior_attempts: int
    issue_signature: str
    directed: bool
    directed_attempts: int
    review: dict[str, Any]


@dataclass
class DraftCoordinator:
    service: Any
    project_path: str | Path
    direction: str
    options: dict[str, Any]
    invoke_stage: StageInvoker
    emit: Optional[EventEmitter]
    revision_issues: Optional[list[str]]
    paths: dict[str, Path]
    author_order: tuple[str, ...]
    paper_stage_order: tuple[str, ...]
    section_by_id: dict[str, Any]
    stage_labels: dict[str, str]
    error_factory: Callable[[str, list[str]], Exception]
    directed_repair_attempts: int
    semantic_stall_attempts: int
    max_attempts: int = 3
    target_stage_issues: dict[str, list[str]] = field(default_factory=dict)
    directed_signatures: dict[str, str] = field(default_factory=dict)
    automatic_consistency_revalidation: bool = False

    async def run(self) -> dict[str, Any]:
        self.options = {**dict(self.options or {}), "research_direction": self.direction}
        from .paper_preparation_errors import guard_paper_preparation

        guard_paper_preparation("draft_contracts", lambda: self.service.prepare(self.project_path, self.options))
        self.max_attempts = self._configured_attempts()
        self._configure_targeted_repairs()
        for stage_id in self.author_order:
            await self._run_stage(stage_id)
        return await self._finalize()

    def _configured_attempts(self) -> int:
        configured = self.options.get("paper_section_revision_rounds")
        if configured is None:
            configured = self.options.get("max_revision_rounds")
        return max(1, min(6, int(configured or 3)))

    def _configure_targeted_repairs(self) -> None:
        self.automatic_consistency_revalidation = False
        targeted = self._normalized_targeted_issues()
        if not targeted:
            return
        explicit = list(dict.fromkeys(stage for issue in targeted
            for stage in self._explicit_target_stages([issue])))
        if not explicit:
            explicit = ["consistency"]
        self.target_stage_issues = self._issues_by_stage(explicit, targeted)
        if "consistency" not in self.target_stage_issues:
            self.automatic_consistency_revalidation = True
            self.target_stage_issues["consistency"] = [
                AUTOMATIC_CONSISTENCY_DIRECTIVE,
                *targeted,
            ]
        self.directed_signatures = {
            stage: self.service.directed_issue_signature(issues)
            for stage, issues in self.target_stage_issues.items()
        }
        from .paper_revision_queue import queue_author_repairs
        queue_author_repairs(self.paths["state"], self.target_stage_issues, self.directed_signatures)

    def _issues_by_stage(self, explicit: list[str], targeted: list[str]) -> dict[str, list[str]]:
        """A mixed manuscript gate must not delegate sibling findings to every author."""
        result = {stage: [] for stage in explicit}
        for issue in targeted:
            stages = self._explicit_target_stages([issue])
            recipients = [stage for stage in stages if stage in result]
            if not recipients:
                recipients = ["consistency"] if stages or global_artifact_issue(issue) else list(explicit)
            for stage in recipients:
                result.setdefault(stage, []).append(issue)
        return {stage: issues for stage, issues in result.items() if issues}

    def _normalized_targeted_issues(self) -> list[str]:
        from .paper_revision_queue import pending_author_repairs
        targeted = list(self.revision_issues or [])
        if targeted:
            from .paper_consistency_findings import implicated_consistency_findings

            review = self.service.validate_complete_draft(self.project_path, require_main=False)
            precise = implicated_consistency_findings(targeted, list(review.get("findings") or []))
            if precise:
                replaced = {str(item.get(field) or "") for item in precise
                            for field in ("validation_issue", "message", "plain_message") if item.get(field)}
                targeted = [issue for issue in targeted if not any(value in issue for value in replaced)]
                targeted.extend("Target artifact: " + target + "\n" + str(item["message"])
                                for item in precise for target in item.get("legal_write_targets") or item.get("target_files") or [])
        targeted = list(dict.fromkeys(canonical_author_feedback(self.paths['root'], issue) for issue in [*targeted,
            *pending_author_repairs(self.paths["state"], self.author_order)]))
        text = " ".join(str(issue) for issue in targeted)
        mentioned_tex = {
            match.casefold()
            for match in re.findall(r"\b[A-Za-z0-9_-]+\.tex\b", text, re.IGNORECASE)
        }
        assembly_only = bool(
            targeted and mentioned_tex == {"main.tex"}
            and re.search(r"\bmissing(?:\s+or\s+empty)?\b[^;\n]*\bmain\.tex\b", text, re.IGNORECASE)
        )
        return [] if assembly_only else targeted

    def _explicit_target_stages(self, targeted: list[str]) -> list[str]:
        targets = self.service.revision_target_paths(targeted)
        if targets:
            return self._stages_from_paths(targeted, targets)
        joined = " ".join(targeted).casefold()
        return [
            stage for stage in self.author_order
            if self._stage_mentioned(stage, joined)
        ]

    def _stages_from_paths(
        self, targeted: list[str], targets: list[str]
    ) -> list[str]:
        explicit, unresolved = [], []
        for target in targets:
            stage = self.service.stage_for_project_relative_target(target)
            if not stage:
                unresolved.append(target)
            elif stage in self.author_order and stage not in explicit:
                explicit.append(stage)
        if unresolved:
            raise self.error_factory("routing", [
                "non-staged paper target requires the bounded artifact editor instead of a section writer: " + target
                for target in unresolved
            ])
        if not explicit and all(
            self.service.stage_for_project_relative_target(target) == "assembly"
            for target in targets
        ):
            targeted.clear()
        return explicit

    def _stage_mentioned(self, stage: str, joined: str) -> bool:
        phrase = stage.replace("_", " ")
        filename = self.section_by_id[stage].filename.casefold() if stage in self.section_by_id else ""
        label = str(self.stage_labels.get(stage) or "").casefold()
        return bool(
            re.search(rf"\b{re.escape(phrase)}\b", joined)
            or (filename and filename in joined)
            or (label and label in joined)
        )

    async def _run_stage(self, stage_id: str) -> None:
        from .paper_revision_queue import complete_author_repair
        state = read_owned_state(self.paths["state"])
        revision = list(self.target_stage_issues.get(stage_id) or [])
        if await self._reuse_if_current(stage_id, state, revision):
            return
        if stage_id == "consistency":
            self.service.assemble(self.project_path)
        run = self._stage_run(stage_id, state, revision)
        self._quarantine_duplicate_blueprint(run)
        if await self._revalidate_without_invocation(run):
            complete_author_repair(self.paths["state"], stage_id)
            return
        self._defer_consistency_to_section_authors(run)
        await self._recover_interrupted_run(run)
        remaining = self._remaining_attempts(run)
        if remaining == 0:
            await self._raise_exhausted(run)
        await self._attempt_stage(run, remaining)
        if not run.review.get("passed"):
            raise self.error_factory(stage_id, run.review.get("issues") or [])
        complete_author_repair(self.paths["state"], stage_id)

    def _defer_consistency_to_section_authors(self, run: StageRun) -> None:
        if run.stage_id != "consistency":
            return
        review = self.service.validate_stage(self.project_path, run.stage_id)
        reviewed_input = run.record.get("reviewed_input_signature") or run.record.get("input_signature")
        sources_changed = bool(reviewed_input and reviewed_input !=
            self.service.stage_input_signature(self.paths, run.stage_id))
        findings = [item for item in review.get("findings") or [] if isinstance(item, dict)
                    and item.get("stage_id") in self.section_by_id
                    and (item.get("category") != "model_consistency" or not sources_changed)]
        if not findings:
            return
        queue_consistency_authors(self.paths['state'], findings, self.service.directed_issue_signature)
        self.service.record_review(self.paths, run.stage_id, review, run.prior_attempts)
        self.service.mark_stage(self.paths, run.stage_id, "revision_required",
                                attempt=run.prior_attempts, review=review,
                                error="cross-section scientific defects require their bounded section authors")
        raise self.error_factory(run.stage_id, [str(item["message"]) for item in findings])

    async def _reuse_if_current(
        self, stage: str, state: dict[str, Any], revision: list[str]
    ) -> bool:
        record = dict(state.get("stages", {}).get(stage) or {})
        from .paper_deferred_rebind import deferred_rebind_current, record_deferred_rebind
        if self.service.stage_is_current(self.paths, state, stage) and not revision:
            await self._notify("paper_stage_reused", stage, attempt=int(record.get("attempts") or 0))
            return True
        if ((self.target_stage_issues and stage not in self.target_stage_issues
                and self.service.stage_outputs_are_current(self.paths, state, stage))
                or (not revision and deferred_rebind_current(self.paths, state, stage))):
            record_deferred_rebind(self.paths, stage)
            await self._notify(
                "paper_stage_reused", stage,
                attempt=int(record.get("attempts") or 0), deferred_input_rebind=True,
            )
            return True
        return False

    def _stage_run(
        self, stage: str, state: dict[str, Any], revision: list[str]
    ) -> StageRun:
        record = dict(state.get("stages", {}).get(stage) or {})
        signature = self.directed_signatures.get(stage, "")
        directed = bool(revision and signature)
        directed_attempts = int(record.get("directed_attempts") or 0) if (
            directed and record.get("directed_issue_signature") == signature
        ) else 0
        current_artifact = self.service.stage_target_semantic_signature(self.paths, stage) if directed else ""
        if (directed_attempts > 0 and current_artifact
                and record.get("directed_artifact_signature")
                and record.get("directed_artifact_signature") != current_artifact):
            directed_attempts = 0
        return StageRun(
            stage, record, revision, int(record.get("attempts") or 0), signature,
            directed, directed_attempts,
            {"passed": False, "issues": list(record.get("review_issues") or revision)},
        )

    def _quarantine_duplicate_blueprint(self, run: StageRun) -> None:
        path = self.paths["blueprint"]
        if run.stage_id != "blueprint" or not path.is_file():
            return
        review = self.service.validate_blueprint(path)
        if not any(str(issue).startswith("blueprint duplicates heading:")
                   for issue in review.get("issues", [])):
            return
        archived = self.paths["paper"] / "revisions" / f"invalid_blueprint_{sha256(path)[:12]}.md"
        archived.parent.mkdir(parents=True, exist_ok=True)
        if not archived.exists():
            shutil.copy2(path, archived)
        path.unlink()
        run.review = review

    async def _revalidate_without_invocation(self, run: StageRun) -> bool:
        from .paper_candidate_revalidation import revalidate_saved_candidate
        if revalidate_saved_candidate(self, run):
            await self._notify("paper_stage_reused", run.stage_id, attempt=run.prior_attempts,
                               revalidated=True, saved_candidate_revalidated=True)
            return True
        refresh = read_owned_state(self.paths["state"]).get("explanation_refresh_requires_model_review")
        if refresh and run.stage_id != "consistency" and not run.revision_issues:
            return await self._validate_existing(run, "candidate_preserved_for_independent_review")
        if run.stage_id != 'consistency' and not run.revision_issues and run.prior_attempts == 0:
            return await self._validate_existing(run, "existing_candidate_revalidated")
        if (run.stage_id == "consistency" and read_owned_state(self.paths["state"]).get(
                "explanation_refresh_requires_model_review")):
            return False
        if automatic_consistency_revalidation(self, run) and await self._validate_existing(run, "cache_only_consistency_reconciled"):
            return True
        status_only = stage_freshness_only(self, run)
        contract_stale = (
            run.record.get("contract_version") is not None
            and run.record.get("contract_version")
            != self.service.stage_contract_version(run.stage_id)
        )
        validator_stale = (
            run.record.get("validator_signature") != self.service.stage_validator_signature(run.stage_id)
            and bound_stage_content(self, run)
        )
        resume_candidate = (
            run.prior_attempts > 0 and not run.revision_issues
            and run.record.get("status") in {"completed", "running", "revision_required", "pending"}
        )
        if status_only and bound_stage_content(self, run) and await self._validate_existing(run, "stale_local_status_reconciled"):
            return True
        if (contract_stale or validator_stale) and (not run.revision_issues or status_only):
            if await self._validate_existing(run, "validator_contract_upgraded"):
                return True
            run.directed_attempts = 0
        if resume_candidate and await self._validate_existing(run, "revalidated"):
            return True
        return False

    async def _validate_existing(self, run: StageRun, reason: str) -> bool:
        outputs = self.service.stage_outputs(self.paths, run.stage_id)
        if not outputs or not all(path.is_file() and path.stat().st_size > 0 for path in outputs):
            return False
        review = self.service.validate_stage(self.project_path, run.stage_id)
        run.review = review
        self.service.record_review(self.paths, run.stage_id, review, run.prior_attempts)
        if not review.get("passed"):
            return False
        self.service.mark_stage(
            self.paths, run.stage_id, "completed",
            attempt=run.prior_attempts, review=review,
        )
        metadata = {"revalidated": True}
        if reason != "revalidated":
            metadata[reason] = True
        await self._notify(
            "paper_stage_reused", run.stage_id,
            attempt=run.prior_attempts, **metadata,
        )
        return True

    async def _recover_interrupted_run(self, run: StageRun) -> None:
        if run.record.get("status") != "running":
            return
        run.prior_attempts = max(0, run.prior_attempts - 1)
        if run.directed:
            run.directed_attempts = max(0, run.directed_attempts - 1)
            self.service._record_directed_attempt(self.paths, run.stage_id, run.issue_signature,
                run.directed_attempts, self.service.stage_target_semantic_signature(self.paths, run.stage_id))
        self.service.mark_stage(
            self.paths, run.stage_id, "pending", attempt=run.prior_attempts,
            error="authoring invocation interrupted before section review",
        )
        await self._notify(
            "paper_stage_resumed", run.stage_id,
            recovered_attempt=True, attempt=run.prior_attempts,
        )

    def _remaining_attempts(self, run: StageRun) -> int:
        if run.directed:
            return max(0, self.directed_repair_attempts - run.directed_attempts)
        return max(0, self.max_attempts - run.prior_attempts)

    async def _raise_exhausted(self, run: StageRun) -> None:
        reason = (
            "directed repair budget exhausted for the unchanged review issue"
            if run.directed
            else f"section revision budget exhausted ({self.max_attempts} attempts)"
        )
        await self._notify(
            "paper_stage_repair_skipped", run.stage_id,
            attempt=run.prior_attempts, directed_repair=run.directed,
            reason=reason, issues=list(run.review.get("issues") or [])[:12],
        )
        raise self.error_factory(run.stage_id, run.review.get("issues") or [reason])

    async def _attempt_stage(self, run: StageRun, remaining: int) -> None:
        last_issue = self.service.directed_issue_signature(run.review.get("issues") or [])
        last_artifact = self.service.stage_target_semantic_signature(
            self.paths, run.stage_id
        ) if last_issue else ""
        no_change, stalls = False, 0
        for local_attempt in range(1, remaining + 1):
            attempt = run.prior_attempts + local_attempt
            directed_attempt = run.directed_attempts + local_attempt
            await self._start_attempt(run, attempt, directed_attempt)
            from .paper_candidate_transaction import author_candidate
            result, run.review = await author_candidate(self, run, attempt, directed_attempt, no_change)
            if result is None:
                if run.review.get("passed"):
                    return
                raise RuntimeError("unreachable interrupted invocation state")
            self.service.record_review(self.paths, run.stage_id, run.review, attempt)
            await self._notify(
                "paper_stage_reviewed", run.stage_id, attempt=attempt,
                passed=bool(run.review.get("passed")),
                issues=list(run.review.get("issues") or [])[:12],
                output_preview=str(result or "")[:400],
            )
            if run.review.get("passed"):
                self.service.mark_stage(
                    self.paths, run.stage_id, "completed", attempt=attempt, review=run.review
                )
                return
            current_issue = self.service.directed_issue_signature(run.review.get("issues") or [])
            current_artifact = getattr(run, 'candidate_signature', '') or self.service.stage_target_semantic_signature(self.paths, run.stage_id)
            stalled = bool(current_issue and current_issue == last_issue and current_artifact == last_artifact)
            self._mark_failed_attempt(run, attempt, stalled)
            if run.stage_id == "consistency" and any(item.get("category") == "model_consistency"
                    for item in run.review.get("findings") or []):
                return
            if stalled:
                stalls += 1
                await self._notify(
                    "paper_stage_stalled", run.stage_id, attempt=attempt,
                    issues=list(run.review.get("issues") or [])[:12],
                    issue_signature=current_issue, artifact_signature=current_artifact,
                )
                if stalls >= self.semantic_stall_attempts or local_attempt >= remaining:
                    return
                no_change = True
                await self._notify(
                    "paper_stage_no_progress_retry", run.stage_id,
                    attempt=attempt, next_attempt=attempt + 1,
                    issues=list(run.review.get("issues") or [])[:12],
                )
            else:
                no_change, stalls = False, 0
                last_issue, last_artifact = current_issue, current_artifact

    async def _start_attempt(
        self, run: StageRun, attempt: int, directed_attempt: int
    ) -> None:
        await self._notify(
            "paper_stage_started", run.stage_id, attempt=attempt,
            maximum_attempts=(run.prior_attempts + self.directed_repair_attempts
                              if run.directed else self.max_attempts),
            directed_repair=run.directed,
        )
        if run.directed:
            self.service._record_directed_attempt(
                self.paths, run.stage_id, run.issue_signature, directed_attempt,
                self.service.stage_target_semantic_signature(self.paths, run.stage_id),
            )
        self.service.mark_stage(self.paths, run.stage_id, "running", attempt=attempt)

    async def _invoke(
        self, run: StageRun, attempt: int, directed_attempt: int, no_change: bool
    ) -> str | None:
        prompt_issues = list(dict.fromkeys([*(run.review.get("issues") or []), *run.revision_issues]))
        if no_change:
            prompt_issues.insert(
                0, "The immediately preceding invocation returned without changing the canonical target. You must edit the listed stage output in place, re-read it, and only then return a concise summary."
            )
        prompt = self.service.build_stage_prompt(
            self.project_path, run.stage_id, self.options,
            revision_issues=prompt_issues,
        )
        outputs = self.service.stage_write_targets(self.paths, run.stage_id)
        before_signature = self.service.stage_target_semantic_signature(self.paths, run.stage_id)
        try:
            return await self.invoke_stage(
                run.stage_id, prompt,
                self.service.invocation_contract(run.stage_id, outputs),
            )
        except (Exception, asyncio.CancelledError) as exc:
            if run.directed:
                self.service._record_directed_attempt(
                    self.paths, run.stage_id, run.issue_signature,
                    run.directed_attempts,
                    self.service.stage_target_semantic_signature(self.paths, run.stage_id),
                )
            self.service.mark_stage(
                self.paths, run.stage_id, "pending",
                attempt=max(run.prior_attempts, attempt - 1),
                error=f"authoring invocation interrupted: {type(exc).__name__}: {exc}",
            )
            await self._notify(
                "paper_stage_interrupted", run.stage_id, attempt=attempt,
                attempt_recovered=True, error=f"{type(exc).__name__}: {exc}"[:2000],
            )
            raise


    def _mark_failed_attempt(self, run: StageRun, attempt: int, stalled: bool) -> None:
        self.service.mark_stage(
            self.paths, run.stage_id, "revision_required",
            attempt=attempt, review=run.review,
            error=("semantic no-progress: unchanged findings and target artifacts"
                   if stalled else "; ".join(run.review.get("issues") or [])),
        )

    async def _finalize(self) -> dict[str, Any]:
        await self._notify("paper_stage_started", "assembly", attempt=1, maximum_attempts=1)
        try:
            main_path = self.service.assemble(self.project_path)
            review = self.service.validate_complete_draft(self.project_path)
        except Exception as exc:
            if hasattr(exc, "issues"):
                await self._notify(
                    "paper_stage_reviewed", "assembly", attempt=1,
                    passed=False, issues=list(exc.issues)[:12],
                )
            raise
        await self._notify(
            "paper_stage_reviewed", "assembly", attempt=1,
            passed=bool(review.get("passed")), issues=list(review.get("issues") or [])[:12],
        )
        if not review["passed"]:
            raise self.error_factory("assembly", review["issues"])
        state = self.service.mark_stage(
            self.paths, "assembly", "completed", attempt=1,
            review={"passed": True, "issues": []},
        )
        now = time.time()
        state.update({
            "status": "completed", "main_sha256": sha256(main_path),
            "completed_at": now, "updated_at": now,
        })
        write_json(self.paths["state"], state)
        return {
            "status": "completed", "main_path": str(main_path),
            "main_sha256": state["main_sha256"],
            "publication_class": state["publication_class"],
            "evidence_mode": state["evidence"]["mode"],
            "submission_eligible": state["evidence"]["submission_eligible"],
            "stages": list(self.author_order),
            "research_direction": self.direction,
        }

    async def _notify(self, event: str, stage_id: str, **extra: Any) -> None:
        if self.emit is None:
            return
        payload = {
            "stage_id": stage_id,
            "stage_label": self.stage_labels.get(stage_id, stage_id),
            "stage_index": self.paper_stage_order.index(stage_id) + 1,
            "stage_total": len(self.paper_stage_order),
            **extra,
        }
        await self.emit(event, payload)
