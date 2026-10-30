"""Expose only explicit paper producer failures to the outer revision gate."""

from typing import Any

from .paper_acceptance_errors import PaperAcceptanceError
from .paper_preparation_errors import PaperPreparationError
from .figure_producer_errors import DeterministicFigureProducerError


def paper_failure_details(error: Exception) -> dict[str, Any] | None:
    """Known figure/paper producers retain scope; generic faults cannot invent it."""
    return error.gate_details() if isinstance(error, (
        DeterministicFigureProducerError, PaperAcceptanceError, PaperPreparationError,
    )) else None
