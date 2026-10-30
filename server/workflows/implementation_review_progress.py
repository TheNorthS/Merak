"""A fresh source-bound independent review may open a new bounded repair scope."""

from pathlib import Path

from ..services.implementation_review_receipt import load_review, review_source_hash


def new_implementation_review_scope(context) -> bool:
    """Do not declare vanished findings resolved; only avoid a false repeated-attempt count."""
    if context.revision_owner.id != 'exp-design':
        return False
    if not context.last_scope_signature or context.scope_signature == context.last_scope_signature:
        return False
    findings = context.diagnostics.get('findings') or []
    if not findings or any(row.get('category') != 'implementation_review' or not row.get('target_files')
                           for row in findings):
        return False
    root = Path(context.run.project_path).resolve()
    receipt = load_review(root)
    if not receipt.get('source_sha256') or receipt['source_sha256'] != review_source_hash(root):
        return False
    reviewed = {str(row.get('id') or '') for row in receipt.get('assessment', {}).get('findings', [])}
    return all(str(row.get('id') or '') in reviewed for row in findings)
