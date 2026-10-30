"""Domain-neutral contracts connecting an accepted idea to executable evidence."""
from __future__ import annotations
from pathlib import Path
from typing import Any

from .method_contract_planning import (
    planned_method_contract as build_planned_method_contract,
    scaffold_method_contract as build_method_scaffold,
)
from .method_contract_persistence import bind_idea_contract, write_planned_contract
from .method_contract_persistence import finalize_from_integration_verdict
from ..contracts.implementation_evidence import IntegrationVerdict
from .research_contract_versions import SELECTED_IDEA_SCHEMA
from .method_contract_normalization import (
    _nonempty_list,
    _normalized,
    _sha256,
    _string_list,
    normalize_claim_evidence_plan,
    implementation_evidence_register_map,  # noqa: F401 - public re-export
    normalize_implementation_evidence,  # noqa: F401 - public re-export
    normalize_mechanism_coverage,
    resolve_implementation_evidence,  # noqa: F401 - public re-export
)


from .method_contract_evidence import (
    _python_symbols,  # noqa: F401 - public re-export
    _safe_json,
)
from .method_contract_validation import (
    validate_claim_plan,
    validate_coverage,
    validate_evidence_selectors,
    validate_implementation_checks,
    validate_evaluation_contract,
    validate_method_header,
    method_validation_result,
    validate_named_records,
)


SELECTED_IDEA_RELATIVE_PATH = Path("ideas") / "SELECTED_IDEA.json"
METHOD_CONTRACT_RELATIVE_PATH = Path("experiments") / "METHOD_CONTRACT.json"


class MethodContractService:
    """Validate traceability without embedding assumptions about a scientific domain."""

    selected_idea_relative_path = SELECTED_IDEA_RELATIVE_PATH
    method_contract_relative_path = METHOD_CONTRACT_RELATIVE_PATH

    def selected_idea_path(self, project_path: str | Path) -> Path:
        return Path(project_path).expanduser().resolve() / self.selected_idea_relative_path

    def method_contract_path(self, project_path: str | Path) -> Path:
        return Path(project_path).expanduser().resolve() / self.method_contract_relative_path

    def scaffold_method_contract(self, selected_idea: str) -> dict[str, Any]:
        return build_method_scaffold(
            selected_idea,
            self.selected_idea_relative_path,
        )

    def planned_method_contract(self, project_path: str | Path) -> dict[str, Any]:
        root = Path(project_path).expanduser().resolve()
        return build_planned_method_contract(
            root,
            self.selected_idea_relative_path,
        )
    def ensure_planned_method_contract(self, project_path: str | Path) -> bool:
        root = Path(project_path).expanduser().resolve()
        path = self.method_contract_path(root)
        return write_planned_contract(path, self.planned_method_contract(root))

    def stamp_method_contract_idea_hash(self, project_path: str | Path) -> bool:
        root = Path(project_path).expanduser().resolve()
        return bind_idea_contract(
            self.method_contract_path(root), self.selected_idea_path(root),
            self.selected_idea_relative_path, finalize=False,
        )

    def finalize_integration_contract(
        self, project_path: str | Path,
        report: dict[str, Any] | None = None,
    ) -> bool:
        root = Path(project_path).expanduser().resolve()
        verdict = IntegrationVerdict.from_report(report or {})
        return finalize_from_integration_verdict(
            self.method_contract_path(root), self.selected_idea_path(root),
            self.selected_idea_relative_path, verdict,
        )


    def validate_selected_idea(
        self,
        project_path: str | Path,
        expected_title: str = "",
    ) -> tuple[bool, list[str], dict[str, Any]]:
        root = Path(project_path).expanduser().resolve()
        path = self.selected_idea_path(root)
        payload, load_error = _safe_json(path)
        issues = [load_error] if load_error else []
        if not payload:
            return False, issues, {"path": str(path), "issues": issues}

        title = str(payload.get("title") or "").strip()
        if int(payload.get("schema") or 0) != SELECTED_IDEA_SCHEMA:
            issues.append(
                "selected idea contract uses an unsupported schema; "
                f"current schema={SELECTED_IDEA_SCHEMA}"
            )
        if str(payload.get("status") or "").strip().lower() != "accepted":
            issues.append("selected idea contract status must be accepted")
        if not title:
            issues.append("selected idea contract has no title")
        if expected_title and _normalized(title) != _normalized(expected_title):
            issues.append(
                f"selected idea contract title does not match accepted Top-1: {expected_title}"
            )
        if not str(payload.get("problem_statement") or "").strip():
            issues.append("selected idea contract has no problem_statement")
        if not str(payload.get("hypothesis") or "").strip():
            issues.append("selected idea contract has no falsifiable hypothesis")

        claims = _nonempty_list(payload.get("claims"))
        mechanisms = _nonempty_list(payload.get("mechanisms"))
        failure_conditions = _string_list(payload.get("falsification_conditions"))
        if not claims:
            issues.append("selected idea contract must declare at least one claim")
        if not mechanisms:
            issues.append("selected idea contract must declare at least one mechanism")
        if not failure_conditions:
            issues.append("selected idea contract must declare falsification_conditions")

        claim_ids, claim_issues = validate_named_records(
            claims, label="claims", required_fields=("statement",)
        )
        mechanism_ids, mechanism_issues = validate_named_records(
            mechanisms,
            label="mechanisms",
            required_fields=("name", "description"),
        )
        issues.extend([*claim_issues, *mechanism_issues])
        from .publication_semantics import validate_publication_semantics
        issues.extend(validate_publication_semantics(payload))

        report_path = root / "ideas" / "novelty_report.md"
        if report_path.is_file() and title:
            report = _normalized(report_path.read_text(encoding="utf-8", errors="replace"))
            if _normalized(title) not in report:
                issues.append("selected idea title is not traceable to ideas/novelty_report.md")

        details = {
            "path": str(path),
            "sha256": _sha256(path),
            "title": title,
            "claim_ids": sorted(claim_ids),
            "mechanism_ids": sorted(mechanism_ids),
            "required_mechanism_ids": sorted(
                str(item.get("id"))
                for item in mechanisms
                if isinstance(item, dict) and item.get("id") and item.get("required", True)
            ),
            "issues": list(dict.fromkeys(issues)),
        }
        return not issues, details["issues"], details

    def _resolve_evidence_path(
        self,
        root: Path,
        raw_path: Any,
        *,
        allow_contract_artifact: bool = False,
    ) -> tuple[Path | None, str]:
        value = str(raw_path or "").strip()
        if not value:
            return None, "implementation evidence has no path"
        relative = Path(value)
        if relative.is_absolute():
            return None, f"implementation evidence path must be project-relative: {value}"
        candidate = (root / relative).resolve()
        try:
            project_relative = candidate.relative_to(root)
        except ValueError:
            return None, f"implementation evidence escapes the project: {value}"
        if not project_relative.parts or project_relative.parts[0].lower() != "experiments":
            return None, f"implementation evidence must live under experiments/: {value}"
        canonical_contract = (
            len(project_relative.parts) == 2
            and project_relative.name.casefold() in {
                "run_spec.json",
                "method_contract.json",
                "implementation_build.json",
                "implementation_blueprint.json",
            }
        )
        if (
            len(project_relative.parts) < 2
            or (
                project_relative.parts[1].lower() not in {"src", "configs", "tests"}
                and not canonical_contract
            )
        ):
            return None, f"implementation evidence must use experiments/src, configs, or tests: {value}"
        if not candidate.is_file() or candidate.stat().st_size == 0:
            return None, f"implementation evidence is missing or empty: {value}"
        return candidate, ""

    def _validate_evidence(
        self,
        root: Path,
        check_id: str,
        evidence: dict[str, Any],
    ) -> tuple[list[str], dict[str, Any]]:
        structured_register = evidence.get("_structured_register") is True
        candidate, path_error = self._resolve_evidence_path(
            root,
            evidence.get("path"),
            allow_contract_artifact=structured_register,
        )
        if path_error or candidate is None:
            return [f"{check_id}: {path_error}"], {"path": str(evidence.get("path") or ""), "passed": False}

        symbols = _string_list(evidence.get("symbols"))
        anchors = _string_list(evidence.get("anchors"))
        config_keys = _string_list(evidence.get("config_keys"))
        data_keys = _string_list(
            evidence.get("data_keys")
            or evidence.get("batch_fields")
            or evidence.get("output_keys")
        )
        issues: list[str] = []
        matched: dict[str, Any] = {
            "path": candidate.relative_to(root).as_posix(),
            "symbols": [],
            "anchors": [],
            "config_keys": [],
            "data_keys": [],
        }
        if not (symbols or anchors or config_keys or data_keys) and not structured_register:
            issues.append(
                f"{check_id}: evidence must declare symbols, anchors, "
                f"config_keys, or data_keys for {matched['path']}"
            )
        if structured_register:
            matched["source_artifact_verified"] = True

        issues.extend(validate_evidence_selectors(
            candidate,
            check_id,
            matched,
            {
                "symbols": symbols,
                "data_keys": data_keys,
                "anchors": anchors,
                "config_keys": config_keys,
            },
        ))

        matched["passed"] = not issues
        return issues, matched

    def validate_method_contract(
        self,
        project_path: str | Path,
        expected_title: str,
        expected_idea_sha256: str = "",
        *,
        allow_planned: bool = False,
    ) -> tuple[bool, list[str], dict[str, Any]]:
        root = Path(project_path).expanduser().resolve()
        idea_ok, idea_issues, idea_details = self.validate_selected_idea(root, expected_title)
        path = self.method_contract_path(root)
        payload, load_error = _safe_json(path)
        issues = list(idea_issues)
        if load_error:
            issues.append(load_error)
        if not payload:
            return False, list(dict.fromkeys(issues)), {
                "path": str(path),
                "selected_idea_contract": idea_details,
                "issues": list(dict.fromkeys(issues)),
            }
        current_idea_hash = str(idea_details.get("sha256") or "")
        status, planned, header_issues = validate_method_header(
            payload,
            expected_title=expected_title,
            expected_path=self.selected_idea_relative_path.as_posix(),
            current_idea_hash=current_idea_hash,
            expected_idea_hash=expected_idea_sha256,
            allow_planned=allow_planned,
        )
        issues.extend(header_issues)
        check_map, check_results, check_issues = validate_implementation_checks(
            payload,
            lambda check_id, evidence: self._validate_evidence(root, check_id, evidence),
            require_checks=not (allow_planned and planned),
        )
        issues.extend(check_issues)
        idea_mechanism_ids = set(idea_details.get("mechanism_ids") or [])
        coverage = normalize_mechanism_coverage(payload.get("mechanism_coverage"))
        covered_ids, coverage_issues = validate_coverage(
            coverage,
            idea_mechanism_ids,
            set(check_map),
            allow_planned=allow_planned,
            planned=planned,
        )
        issues.extend(coverage_issues)
        missing_mechanisms = set(
            idea_details.get("required_mechanism_ids") or []
        ) - covered_ids
        if missing_mechanisms and not (allow_planned and planned):
            issues.append(
                "required accepted-idea mechanism(s) are not implemented: "
                + ", ".join(sorted(missing_mechanisms))
            )
        idea_claim_ids = set(idea_details.get("claim_ids") or [])
        claim_plan = normalize_claim_evidence_plan(
            payload.get("claim_evidence_plan")
        )
        covered_claims, claim_issues = validate_claim_plan(
            claim_plan, idea_claim_ids
        )
        issues.extend(claim_issues)
        missing_claims = idea_claim_ids - covered_claims
        if missing_claims:
            issues.append(
                "accepted-idea claim(s) have no evidence plan: "
                + ", ".join(sorted(missing_claims))
            )
        issues.extend(_contract_publication_issues(
            payload, root=root, expected_title=expected_title,
        ))
        return method_validation_result(
            idea_ok=idea_ok, issues=issues, path=path,
            path_hash=_sha256(path), status=status, planned=planned,
            expected_title=expected_title, idea_details=idea_details,
            check_results=check_results, covered_mechanisms=covered_ids,
            covered_claims=covered_claims,
        )


method_contract_service = MethodContractService()


def _contract_publication_issues(
    payload: dict[str, Any], *, root: Path, expected_title: str,
) -> list[str]:
    from .scientific_scene import validate_scientific_scene

    issues = [
        *validate_evaluation_contract(payload, root=root, expected_title=expected_title),
    ]
    issues.extend(validate_scientific_scene(payload.get('scientific_scene')))
    return issues
