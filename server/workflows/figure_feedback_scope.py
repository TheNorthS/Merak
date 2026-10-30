"""Bind researcher figure feedback to one unambiguous model asset."""

from __future__ import annotations

import re


def scoped_figure_feedback(assets: list[str], feedback: str) -> dict[str, str]:
    """Do not grant every figure a retry for one free-form checkpoint note."""
    message = feedback.strip()
    identities = sorted({identity for identity in assets if identity})
    if not message or not identities:
        return {}
    if len(identities) == 1:
        return {identities[0]: message}
    mentioned = [
        identity for identity in identities
        if re.search(
            rf"(?<![A-Za-z0-9_-]){re.escape(identity)}(?![A-Za-z0-9_-])",
            message, re.IGNORECASE,
        )
    ]
    return {mentioned[0]: message} if len(mentioned) == 1 else {}
