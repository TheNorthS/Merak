"""Native review keeps explicit transport selection, complete responses, and a no-tool boundary."""

import asyncio
from types import SimpleNamespace

import pytest

from server.agent.model_types import LLMResponse, StreamChunk, ToolCall
from server.services.native_review_transport import call_native_review


class Provider:
    model = 'test-vision'
    streaming_enabled = True

    def __init__(self, chunks):
        self.chunks, self.calls, self.closed = chunks, [], False

    async def chat_stream(self, messages, **options):
        self.calls.append(('stream', messages, options))
        try:
            for chunk in self.chunks:
                if isinstance(chunk, Exception):
                    raise chunk
                if chunk is None:
                    await asyncio.Event().wait()
                yield chunk
        finally:
            self.closed = True

    async def chat(self, messages, **options):
        self.calls.append(('non_stream', messages, options))
        return LLMResponse(content='{"ok":true}')


async def activity():
    return None


@pytest.mark.asyncio
async def test_stream_preserves_images_json_and_usage_and_observes_real_text():
    observed = []
    async def observe():
        observed.append('text')
    provider = Provider([StreamChunk('text', '{"ok":'), StreamChunk('text', 'true}'),
        StreamChunk('usage', usage={'output_tokens': 4}), StreamChunk('finish', finish_reason='stop'), StreamChunk('done')])
    messages = [SimpleNamespace(content=[{'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,pixels'}}])]
    response = await call_native_review(provider, messages, observe)
    assert response.content == '{"ok":true}' and response.usage['output_tokens'] == 4
    assert len(observed) == 2 and provider.closed
    assert provider.calls == [('stream', messages, {'tools': None, 'temperature': 0.0, 'max_tokens': 8192})]


@pytest.mark.asyncio
async def test_nonstream_configuration_is_not_overridden():
    provider = Provider([])
    provider.streaming_enabled = False
    assert (await call_native_review(provider, [], activity)).content == '{"ok":true}'
    assert provider.calls[0][0] == 'non_stream'


@pytest.mark.asyncio
@pytest.mark.parametrize('reason', ['length', 'max_tokens', 'content_filter'])
async def test_nonstream_complete_json_with_truncated_finish_is_not_a_verdict(reason):
    calls = []
    async def chat(*args, **kwargs):
        calls.append(1)
        return LLMResponse(content='{"ok":true}', stop_reason=reason)
    provider = SimpleNamespace(streaming_enabled=False, chat=chat)
    with pytest.raises(RuntimeError, match='incomplete'):
        await call_native_review(provider, [], activity)
    assert len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('tail', [[], [StreamChunk('finish', finish_reason='stop')],
    [StreamChunk('finish', finish_reason='length'), StreamChunk('done')],
    [RuntimeError('connection interrupted')],
    [StreamChunk('tool_call_delta', '0')],
    [StreamChunk('tool_call_end', tool_call=ToolCall('1', 'Edit', {}))]])
async def test_partial_cutoff_tool_or_disconnect_never_becomes_verdict_or_replay(tail):
    provider = Provider([StreamChunk('text', '{"ok":true}'), *tail])
    with pytest.raises(RuntimeError):
        await call_native_review(provider, [], activity)
    assert len(provider.calls) == 1 and provider.closed


@pytest.mark.asyncio
async def test_cancellation_closes_transport_without_replay():
    provider = Provider([StreamChunk('text', '{'), None])
    task = asyncio.create_task(call_native_review(provider, [], activity))
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert provider.closed and len(provider.calls) == 1


@pytest.mark.asyncio
async def test_native_invocation_records_stream_mode_in_hash_bound_route(tmp_path, monkeypatch):
    import hashlib
    import json
    from server.agent import model_router
    from server.services.api_visual_reviewer import ApiVisualReviewer

    provider = Provider([StreamChunk('text', '{"ok":true}'),
        StreamChunk('finish', finish_reason='stop'), StreamChunk('done')])
    route = ('test-api', provider, 'test/test-vision')
    monkeypatch.setattr(model_router, 'get_provider_route', lambda role: route)
    monkeypatch.setattr(model_router, 'get_isolated_provider_route', lambda role: route)
    result = await ApiVisualReviewer().invoke(project_path=tmp_path, prompt='Review evidence',
        purpose='stream-test', schema={'type': 'object'})
    from pathlib import Path
    meta = json.loads((Path(result.trace_path) / 'meta.json').read_bytes())
    assert meta['success'] and meta['response_mode'] == 'stream'
    assert meta['reviewer_route']['response_mode'] == 'stream'
    encoded = json.dumps(meta['reviewer_route'], ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    assert meta['reviewer_route_sha256'] == hashlib.sha256(encoded.encode()).hexdigest()
