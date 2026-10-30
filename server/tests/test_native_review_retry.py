"""Transient no-output review failures recover without replaying partial responses."""

import asyncio

import pytest

from server.agent.model_types import StreamChunk
from server.agent.remote_errors import RemoteCallError
from server.services.native_review_transport import call_native_review


class Provider:
    streaming_enabled = True
    model = 'local-test'

    def __init__(self, attempts):
        self.attempts, self.calls, self.closed = attempts, 0, 0

    async def chat_stream(self, messages, **options):
        assert options['tools'] is None
        current = self.attempts[self.calls]
        self.calls += 1
        try:
            for item in current:
                if isinstance(item, BaseException):
                    raise item
                yield item
        finally:
            self.closed += 1


async def activity():
    return None


def failure(status=502, delay=0):
    return RemoteCallError('test-api', status, retry_after=delay)


def success():
    return [StreamChunk('text', '{"ok":true}'), StreamChunk('finish', finish_reason='stop'), StreamChunk('done')]


@pytest.mark.asyncio
async def test_transient_no_output_failures_retry_exact_request_and_record_attempts():
    provider, records = Provider([[failure()], [failure(503)], success()]), []
    result = await call_native_review(provider, [], activity, records.append)
    assert result.content == '{"ok":true}' and provider.calls == provider.closed == 3
    assert [item['http_status'] for item in records] == [502, 503]
    assert all(item['retry_scheduled'] and not item['received_text'] for item in records)


@pytest.mark.asyncio
@pytest.mark.parametrize('prefix,status,delay', [([], 401, 0), ([], 400, 0), ([], 429, 60),
    ([StreamChunk('text', '{')], 502, 0)])
async def test_auth_invalid_requests_long_retry_after_and_partial_output_are_not_replayed(prefix, status, delay):
    provider = Provider([[*prefix, failure(status, delay)]])
    with pytest.raises(RemoteCallError):
        await call_native_review(provider, [], activity)
    assert provider.calls == provider.closed == 1


@pytest.mark.asyncio
async def test_exhaustion_reports_actual_attempts_and_never_returns_partial_verdict():
    provider = Provider([[failure()], [failure()], [failure()]])
    with pytest.raises(RemoteCallError) as caught:
        await call_native_review(provider, [], activity)
    assert caught.value.model_request_attempts == 3
    assert provider.calls == provider.closed == 3


@pytest.mark.asyncio
async def test_shared_deadline_cancels_backoff_without_starting_another_request():
    provider = Provider([[failure(delay=30)], success()])
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(call_native_review(provider, [], activity), timeout=.02)
    assert provider.calls == provider.closed == 1


@pytest.mark.asyncio
async def test_user_cancellation_never_retries():
    provider = Provider([[asyncio.CancelledError()]])
    with pytest.raises(asyncio.CancelledError):
        await call_native_review(provider, [], activity)
    assert provider.calls == provider.closed == 1
