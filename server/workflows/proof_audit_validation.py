"""Proof-source graph, semantic fingerprint, and artifact validation."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from .review_models import Verdict


def _api() -> Any:
    from . import review_audit

    return review_audit


_PROOF_ENVIRONMENT_RE = re.compile(
    r"\\begin\s*\{\s*(theorem|lemma|proposition|corollary|proof)\*?\s*\}",
    re.IGNORECASE,
)
_TEX_INCLUDE_RE = re.compile(
    r"\\(?:input|include|subfile)\s*\{([^{}]+)\}",
    re.IGNORECASE,
)
_PROOF_GENERATED_TEX = frozenset({"proof_audit_report.tex"})


def _reachable_paper_tex(
    paper_root: Path,
) -> tuple[list[tuple[Path, bytes, str]], list[str]]:
    """Resolve the static TeX include graph rooted at paper/main.tex."""
    main = (paper_root / "main.tex").resolve()
    if not main.is_file():
        # Persisting PROOF_AUDIT.json creates ``paper/`` even for service-level
        # audit inputs that contain no manuscript source.  Keep the no-source
        # detector stable across that write: an entirely TeX-free directory is
        # simply a no-theorems case.  Conversely, orphan authored TeX files with
        # no entrypoint are an unreadable manuscript and must remain blocking.
        authored_tex = [
            path
            for path in paper_root.rglob("*.tex")
            if path.name.casefold() not in _PROOF_GENERATED_TEX
            and "revisions" not in {part.casefold() for part in path.parts}
        ]
        if not authored_tex:
            return [], []
        return [], [f"{main}: missing main TeX entrypoint"]
    pending = [main]
    seen: set[Path] = set()
    sources: list[tuple[Path, bytes, str]] = []
    errors: list[str] = []
    while pending:
        path = pending.pop()
        if path in seen:
            continue
        seen.add(path)
        try:
            path.relative_to(paper_root)
        except ValueError:
            errors.append(f"{path}: included TeX source escapes paper directory")
            continue
        try:
            raw = path.read_bytes()
            text = raw.decode("utf-8-sig")
        except (OSError, UnicodeError) as exc:
            errors.append(f"{path}: {type(exc).__name__}: {exc}")
            continue
        inspected = re.sub(r"(?m)(?<!\\)%.*$", "", text)
        sources.append((path, raw, inspected))
        children: list[Path] = []
        for match in _TEX_INCLUDE_RE.finditer(inspected):
            value = match.group(1).strip()
            if not value or "\\" in value:
                continue
            relative = Path(value)
            if not relative.suffix:
                relative = relative.with_suffix(".tex")
            candidates = [
                (path.parent / relative).resolve(),
                (paper_root / relative).resolve(),
            ]
            child = next((candidate for candidate in candidates if candidate.is_file()), None)
            if child is None:
                errors.append(f"{path}: included TeX source is missing: {value}")
                continue
            try:
                child.relative_to(paper_root)
            except ValueError:
                errors.append(f"{path}: included TeX source escapes paper directory: {value}")
                continue
            children.append(child)
        pending.extend(reversed(sorted(set(children), key=lambda item: item.as_posix().casefold())))
    return sorted(sources, key=lambda item: item[0].as_posix().casefold()), errors


def proof_source_bundle(
    project_path: str | Path,
) -> tuple[str, dict[str, str], list[Path], int, list[str]]:
    """Hash the exact theorem-bearing TeX inputs declared to proof-checker.

    Paths in ``audited_input_hashes`` are relative to the paper directory, as
    required by the proof-checker assurance contract.  The aggregate digest is
    also persisted so a build attestation can be checked without trusting the
    reviewer payload.
    """
    root = Path(project_path).expanduser().resolve()
    paper_root = root / "paper"
    paths: list[Path] = []
    input_hashes: dict[str, str] = {}
    environment_count = 0
    errors: list[str] = []
    if not paper_root.is_dir():
        digest = hashlib.sha256(b"{}").hexdigest()
        return digest, input_hashes, paths, environment_count, errors

    reachable_sources, reachable_errors = _reachable_paper_tex(paper_root)
    errors.extend(reachable_errors)
    for path, raw, inspected in reachable_sources:
        if (
            "revisions" in {part.casefold() for part in path.parts}
            or path.name.casefold() in _PROOF_GENERATED_TEX
        ):
            continue
        matches = list(_PROOF_ENVIRONMENT_RE.finditer(inspected))
        if not matches:
            continue
        resolved = path.resolve()
        relative = resolved.relative_to(paper_root).as_posix()
        paths.append(resolved)
        input_hashes[relative] = "sha256:" + hashlib.sha256(raw).hexdigest()
        environment_count += len(matches)

    encoded = json.dumps(
        input_hashes,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return (
        hashlib.sha256(encoded).hexdigest(),
        input_hashes,
        paths,
        environment_count,
        errors,
    )


_PROOF_SEMANTIC_VOLATILE_KEYS = frozenset({
    "audit_runtime_signature",
    "created_at",
    "generated_at",
    "model_name",
    "policy_sha256",
    "proof_audit_sha256",
    "proof_semantic_sha256",
    "reviewer_model",
    "reviewer_route_sha256",
    "session_id",
    "thread_id",
    "timestamp",
    "trace_path",
    "updated_at",
})


def _normalize_proof_finding(value: Any) -> Any:
    """Canonicalize proof findings while excluding operational churn."""

    if isinstance(value, dict):
        normalized: dict[str, Any] = {}
        for raw_key, item in sorted(value.items(), key=lambda pair: str(pair[0])):
            key = str(raw_key)
            folded = key.casefold()
            if (
                folded in _PROOF_SEMANTIC_VOLATILE_KEYS
                or folded.endswith("_sha256")
            ):
                continue
            normalized[key] = _normalize_proof_finding(item)
        return normalized
    if isinstance(value, (list, tuple, set)):
        items = [_normalize_proof_finding(item) for item in value]
        return sorted(
            items,
            key=lambda item: json.dumps(
                item,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            ),
        )
    if isinstance(value, str):
        return " ".join(value.split())
    return value


def proof_semantic_sha256(
    proof_source_bundle_sha256: str,
    proof: dict[str, Any],
) -> str:
    """Bind progress to theorem sources plus normalized findings/verdict."""

    details = proof.get("details")
    if not isinstance(details, dict):
        details = {"adjudication": str(details or "")}
    semantic = {
        "proof_source_bundle_sha256": str(proof_source_bundle_sha256 or ""),
        "verdict": str(proof.get("verdict") or "").strip().upper(),
        "reason_code": str(proof.get("reason_code") or "").strip().casefold(),
        "method": str(proof.get("method") or "").strip().casefold(),
        "findings": _normalize_proof_finding(details),
        "evidence": _normalize_proof_finding(proof.get("evidence") or []),
    }
    encoded = json.dumps(
        semantic,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def validate_proof_audit_artifact(
    project_path: str | Path, *, run_id: str = "", evidence_mode: str = "",
    executor_model: str = "", build: dict[str, Any] | None = None,
    proof: dict[str, Any] | None = None, proof_bytes: bytes | None = None,
) -> tuple[list[str], dict[str, Any]]:
    del executor_model
    root = Path(project_path).expanduser().resolve()
    proof_path = root / "paper" / "PROOF_AUDIT.json"
    issues: list[str] = []
    proof, loaded_bytes = _load_proof(proof_path, proof, proof_bytes, issues)
    build = _load_build(root, build)
    source_hash, input_hashes, source_paths, theorem_count, source_errors = (
        proof_source_bundle(root)
    )
    semantic_hash = proof_semantic_sha256(source_hash, proof) if proof else ""
    policy_hash = _proof_policy_hash()
    if source_errors:
        issues.append("proof-checker could not read current TeX sources")
    if proof:
        _validate_proof_metadata(
            proof, run_id, evidence_mode, source_hash, input_hashes,
            semantic_hash, policy_hash, build, issues,
        )
        _validate_proof_verdict(
            root, proof, theorem_count, source_errors, issues
        )
    _validate_build_binding(
        root, build, loaded_bytes, source_hash, semantic_hash, policy_hash, issues
    )
    verdict = str(proof.get("verdict") or "").upper()
    return list(dict.fromkeys(issues)), {
        "valid": not issues, "path": str(proof_path), "verdict": verdict,
        "reason_code": str(proof.get("reason_code") or ""),
        "method": str(proof.get("method") or ""),
        "session_id": str(proof.get("session_id") or proof.get("thread_id") or ""),
        "reviewer_model": str(proof.get("reviewer_model") or proof.get("model_name") or ""),
        "proof_source_bundle_sha256": source_hash,
        "proof_semantic_sha256": semantic_hash, "policy_sha256": policy_hash,
        "audited_input_hashes": input_hashes, "source_count": len(source_paths),
        "formal_environment_count": theorem_count,
    }


def _load_proof(
    path: Path, proof: dict[str, Any] | None, proof_bytes: bytes | None,
    issues: list[str],
) -> tuple[dict[str, Any], bytes | None]:
    loaded = proof_bytes
    if proof is None:
        try:
            loaded = path.read_bytes()
            proof = json.loads(loaded.decode("utf-8-sig"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            proof = {}
            issues.append(
                "proof-checker artifact is missing or invalid: "
                f"{type(exc).__name__}"
            )
    if not isinstance(proof, dict):
        issues.append("proof-checker artifact is not a JSON object")
        proof = {}
    return proof, loaded


def _load_build(root: Path, build: dict[str, Any] | None) -> dict[str, Any]:
    if build is not None:
        return build if isinstance(build, dict) else {}
    path = root / "audit-results" / "AUDIT_BUILD.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _proof_policy_hash() -> str:
    return _api().audit_policy_sha256("proof-checker")


def _validate_proof_metadata(
    proof: dict[str, Any], run_id: str, evidence_mode: str,
    source_hash: str, input_hashes: dict[str, str], semantic_hash: str,
    policy_hash: str, build: dict[str, Any], issues: list[str],
) -> None:
    if proof.get("audit_skill") != "proof-checker":
        issues.append("proof audit does not identify /proof-checker")
    if proof.get("managed_by") != "merak_audit_chain":
        issues.append("proof audit is not runtime-managed")
    if proof.get("policy_loaded") is not True:
        issues.append("proof-checker policy was not recorded as loaded")
    if not policy_hash or str(proof.get("policy_sha256") or "") != policy_hash:
        issues.append("proof-checker policy provenance is missing or stale")
    if run_id and str(proof.get("run_id") or "") != run_id:
        issues.append("proof audit belongs to a different workflow run")
    if evidence_mode and str(proof.get("evidence_mode") or "").casefold() != evidence_mode.casefold():
        issues.append("proof audit evidence mode does not match the workflow")
    if str(proof.get("proof_source_bundle_sha256") or "") != source_hash:
        issues.append("proof audit is stale relative to theorem-bearing sources")
    if not isinstance(proof.get("audited_input_hashes"), dict) or proof.get("audited_input_hashes") != input_hashes:
        issues.append("proof audit input hashes do not match current theorem-bearing sources")
    if _semantic_contract(proof, build) and str(proof.get("proof_semantic_sha256") or "") != semantic_hash:
        issues.append("proof audit semantic fingerprint does not match its findings")


def _semantic_contract(proof: dict[str, Any], build: dict[str, Any]) -> bool:
    try:
        proof_schema = int(proof.get("schema") or 0)
        build_schema = int(build.get("schema") or 0)
    except (TypeError, ValueError):
        proof_schema = build_schema = 0
    return bool(
        proof_schema >= 2 or build_schema >= 4
        or proof.get("proof_semantic_sha256") or build.get("proof_semantic_sha256")
    )


def _validate_proof_verdict(
    root: Path, proof: dict[str, Any], theorem_count: int,
    source_errors: list[str], issues: list[str],
) -> None:
    verdict = str(proof.get("verdict") or "").upper()
    try:
        Verdict(verdict)
    except ValueError:
        issues.append("proof audit has an invalid machine-readable verdict")
    method = str(proof.get("method") or "")
    reason = str(proof.get("reason_code") or "")
    if verdict == Verdict.NOT_APPLICABLE.value:
        if theorem_count != 0 or source_errors:
            issues.append("proof audit declared NOT_APPLICABLE despite formal proof content")
        if method != "deterministic_detector" or reason != "no_theorems":
            issues.append("proof NOT_APPLICABLE verdict lacks the no-theorems detector provenance")
        return
    if verdict == Verdict.BLOCKED.value and reason == "source_unreadable":
        if method != "deterministic_detector" or not source_errors:
            issues.append("proof source-unreadable verdict lacks detector provenance")
        return
    if theorem_count == 0 and not source_errors:
        issues.append("proof audit should be NOT_APPLICABLE when no formal proof content exists")
    if method != "model":
        issues.append("proof audit lacks an independent model verdict")
    _validate_model_proof(root, proof, verdict, issues)


def _validate_model_proof(
    root: Path, proof: dict[str, Any], verdict: str, issues: list[str]
) -> None:
    session_id = str(proof.get("session_id") or proof.get("thread_id") or "").strip()
    model = str(proof.get("reviewer_model") or proof.get("model_name") or "").strip()
    if not session_id:
        issues.append("proof audit has no durable reviewer session")
    if not model:
        issues.append("proof audit has no reviewer model identity")
    trace_path = str(proof.get("trace_path") or "").strip()
    trace_dir = Path(trace_path) if trace_path else Path()
    if trace_path and not trace_dir.is_absolute():
        trace_dir = root / trace_dir
    try:
        trace_dir = trace_dir.resolve()
        trace_dir.relative_to(root)
    except (OSError, ValueError):
        trace_dir = Path()
    if not trace_path or not trace_dir.is_dir() or not all(
        (trace_dir / name).is_file() for name in ("meta.json", "input.txt", "output.txt")
    ):
        issues.append("proof audit has no durable reviewer trace")
    details = proof.get("details") if isinstance(proof.get("details"), dict) else {}
    try:
        audited_count = int(details.get("theorems_audited") or 0)
    except (TypeError, ValueError):
        audited_count = 0
    if audited_count <= 0:
        issues.append("proof audit did not record any audited theorem or proof")
    proof_issues = details.get("issues") if isinstance(details.get("issues"), list) else []
    severities = {str(item.get("severity") or "").upper()
                  for item in proof_issues if isinstance(item, dict)} & {"FATAL", "CRITICAL"}
    if severities and verdict not in {Verdict.FAIL.value, Verdict.BLOCKED.value, Verdict.ERROR.value}:
        issues.append("proof audit verdict contradicts open FATAL/CRITICAL issues")
    if verdict == Verdict.PASS.value and proof_issues:
        issues.append("proof audit PASS retains unresolved proof issues")


def _validate_build_binding(
    root: Path, build: dict[str, Any], proof_bytes: bytes | None,
    source_hash: str, semantic_hash: str, policy_hash: str,
    issues: list[str],
) -> None:
    if not build:
        issues.append("proof audit build attestation is missing")
        return
    current_audit_hash, _ = _api().audit_source_bundle(root)
    if str(build.get("source_bundle_sha256") or "") != current_audit_hash:
        issues.append("proof audit build is stale relative to current sources")
    if str(build.get("proof_source_bundle_sha256") or "") != source_hash:
        issues.append("proof source bundle does not match AUDIT_BUILD.json")
    if str(build.get("proof_policy_sha256") or "") != policy_hash:
        issues.append("proof-checker policy does not match AUDIT_BUILD.json")
    if _semantic_contract({}, build) and str(build.get("proof_semantic_sha256") or "") != semantic_hash:
        issues.append("proof semantic fingerprint does not match AUDIT_BUILD.json")
    current_hash = hashlib.sha256(proof_bytes).hexdigest() if proof_bytes else ""
    if not str(build.get("proof_audit_sha256") or "") or str(build.get("proof_audit_sha256") or "") != current_hash:
        issues.append("PROOF_AUDIT.json does not match AUDIT_BUILD.json")
