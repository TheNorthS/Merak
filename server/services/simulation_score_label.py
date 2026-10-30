"""Distinguish generated scenario coordinates from measured endpoint values."""


def scenario_score_label(_metric: str) -> str:
    """Assigned construction values do not inherit an unmeasured endpoint's scale."""
    return 'Assigned unitless scenario score'
