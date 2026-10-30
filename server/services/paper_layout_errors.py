"""Retain exact print defects after the bounded local producer repair budget."""

from __future__ import annotations

import copy
from typing import Any

from .paper_preparation_errors import PaperPreparationError


class PaperPublicationLayoutError(PaperPreparationError):
    """A layout defect is not an instruction to regenerate scientific prose."""

    def __init__(self, issues: list[str], findings: list[dict[str, Any]], *, attempts: int) -> None:
        self.operation = 'publication_layout'
        self.issues = list(issues)
        self.findings = copy.deepcopy(findings)
        self.attempts = attempts
        RuntimeError.__init__(self, 'Compiled paper failed the publication layout contract: '
                              + '; '.join(self.issues[:12]))

    def gate_details(self) -> dict[str, Any]:
        findings = copy.deepcopy(self.findings)
        return {'issues': list(self.issues), 'findings': findings,
                'error_category': 'paper_publication_layout', 'retryable': False,
                'local_layout_attempts': self.attempts, 'stopped_for_deterministic_stage': True,
                'repair_scope': {'finding_ids': [row['id'] for row in findings],
                                 'target_files': sorted({path for row in findings for path in row['target_files']}),
                                 'asset_ids': sorted({asset for row in findings for asset in row['asset_ids']})}}
