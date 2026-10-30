"""Node-specific model streaming timeout policy."""

from server.workflows.node_execution_invocation import (
    node_output_token_budget,
    node_partial_stream_timeout,
)


def test_figure_payload_gets_longer_first_chunk_budget() -> None:
    assert node_partial_stream_timeout("figure") == 180.0
    assert node_partial_stream_timeout("exp-design") == 60.0
    assert node_partial_stream_timeout("paper") == 90.0
    assert node_partial_stream_timeout("lit") is None


def test_figure_source_has_a_larger_output_budget() -> None:
    assert node_output_token_budget("figure") == 16_384
    assert node_output_token_budget("paper") == 8_192
