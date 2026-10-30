"""Bound draft audits to complete canonical content with explicit unread bulk evidence."""

import hashlib
from pathlib import Path


_BULK_RECORDS = frozenset({"run_ledger.csv", "runtime_artifacts.json", "run_level_results.csv",
    "latency_samples.csv", "raw_predictions.jsonl", "raw_measurements.jsonl", "raw_checkpoints.jsonl",
    "provenance_join_audit.csv", "data_manifest.csv"})
_MANIFESTS = frozenset({"figures/FIGURE_MANIFEST.json", "figures/SCIENTIFIC_ASSET_PLAN.json"})
_CODE_LAYERS = frozenset({"experiment-audit", "paper-claim-audit"})
MAX_DRAFT_AUDIT_BYTES = 650_000


def draft_audit_evidence(root: Path, paths: list[Path], skill: str, *, allow_partition: bool = False) -> tuple[str, list[Path], str]:
    """Never silently truncate a source or claim that hash-only data was read."""
    from .review_audit import _source_bundle

    selected, excluded, seen = [], [], {}
    root = root.resolve()
    from .audit_matrix_scope import matrix_scope, exclusion_reason
    current_matrix = matrix_scope(root)
    for path in paths:
        relative = path.relative_to(root).as_posix()
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        reason = exclusion_reason(relative, current_matrix)
        if relative in _MANIFESTS and not reason:
            reason = "rendering registry; current manuscript, captions and independent visual review are included"
        elif '/reproducibility/replay/' in relative and path.name in {'SOURCE_INDEX.json', 'inputs.json', 'replay.py'}:
            reason = "replay capsule inventory/input bulk; exact reconstruction receipt and numerical constructors are included"
        elif relative == "literature/SEARCH_EVIDENCE.json" and skill not in {"citation-audit", "kill-argument"}:
            reason = "retrieval receipts are inspected by the citation audit"
        elif relative.startswith("experiments/results/templates/"):
            reason = "unexecuted template; canonical current result files are included"
        elif relative.startswith("experiments/results/") and path.name in _BULK_RECORDS:
            reason = "bulk raw records; not independently inspected row by row in this draft audit"
        elif relative.startswith("experiments/src/") and skill not in _CODE_LAYERS:
            reason = "implementation code inspected by the experiment audit; this layer uses contracts and reported evidence"
        # Bibliography paths are explicit compilation inputs. Keep both copies so
        # each audit batch can inspect the compiled file as well as its source.
        if not reason and digest in seen and path.suffix.casefold() != '.bib':
            reason = f"byte-identical content is fully included as {seen[digest]}"
        if reason:
            excluded.append(f"- {relative}: {path.stat().st_size} bytes, sha256={digest}; {reason}")
        else:
            selected.append(path)
            seen[digest] = relative
    total = sum(path.stat().st_size for path in selected if path.suffix.casefold() not in {".pdf", ".png", ".svg"})
    if total > MAX_DRAFT_AUDIT_BYTES and not allow_partition:
        raise ValueError(f"Draft audit canonical evidence exceeds its complete-content budget ({total} bytes); split the audit before retrying")
    from .audit_matrix_scope import compact_exclusions
    scope = ("\n## Explicit draft audit coverage\nThis invocation includes complete selected canonical manuscript, "
        "The current accepted_matrix and independent-matrix-audit report are shared across batches when present. "
        "A frozen METHOD_CONTRACT or RUN_SPEC may retain authoring-time pending declarations; later current "
        "runtime receipts are the evidence of completed checks. Compare the matrix IDs, checked scope, input "
        "hashes and actual passed/issues fields. Do not demand editing immutable source contracts to mark "
        "later runtime completion or treat a pending authoring note alone as disproving a bound passing report. "
        "contracts, reported results, generator and applicable implementation files. All original files remain "
        "in the full audit source binding, but the following inventory is provenance only, NOT semantic evidence. "
        "You have no tools to open excluded files. Do not claim exhaustive raw-record verification. Retain this "
        "coverage limitation in your summary; use WARN or FAIL as appropriate. Unverified claims must remain "
        "qualified. If an excluded record is essential to deciding a concrete integrity defect, report that "
        "unresolved defect rather than asserting PASS. Publication readiness remains false.\n"
        + compact_exclusions(root, skill, excluded))
    source_hash, selected = _source_bundle(root, selected)
    if skill == "citation-audit":
        scope += ("\nUse included SEARCH_EVIDENCE records as provenance of prior external retrieval, never as proof "
            "of unavailable full texts. Separate unknown/unverified metadata from an observed fabricated citation. "
            "This stateless pass has no network tools: disclose verification limits and use WARN/BLOCKED as appropriate; "
            "ERROR denotes an execution/parser failure, not a lack of external access. Incorrect or fabricated "
            "citations remain draft_blockers and must not be waived.")
    return source_hash, selected, scope
