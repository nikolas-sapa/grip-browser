import asyncio
from unittest.mock import AsyncMock

import pytest

from grip.adapters.base import LLMResponse, LLMUsage, ToolCall
from grip.errors.types import BrowserError, ErrorType, GripError, RecoveryAction
from grip.runner import Runner
from grip.trace import Trace
from tests.unit.test_runner import FakePage, make_llm


def batch(*calls):
    return LLMResponse(None, None, LLMUsage('openai', total_tokens=10), tool_calls=calls)


def results(runner):
    return [m for m in runner._messages if m['role'] == 'tool']


async def test_three_call_batch_order_complete_history_usage_once():
    calls = (ToolCall('type', {'target': 'Field', 'text': 'value'}, 'a'),
             ToolCall('click', {'target': 'Submit'}, 'b'),
             ToolCall('done', {'result': 'ok'}, 'c'))
    llm = make_llm([batch(*calls)])
    runner = Runner(llm, FakePage(['page']), Trace(), max_steps=3)
    runner._dispatch = AsyncMock(return_value='ok')
    result = await runner.run('submit')
    assert result.success is True and result.tokens == 10 and result.model_calls == 1
    assert [c.args[0] for c in runner._dispatch.await_args_list] == ['type', 'click', 'done']
    assert [m['tool_call_id'] for m in results(runner)] == ['a', 'b', 'c']
    assert runner._trace.model_calls == 1


@pytest.mark.parametrize('calls', [
    (ToolCall('click', {'target': 'A'}, 'same'), ToolCall('read', {}, 'same')),
    (ToolCall('click', {'target': 'A'}), ToolCall('read', {}, '')),
    (ToolCall('done', {'result': 'ok'}), ToolCall('click', {'target': 'A'})),
    (ToolCall('done', {'result': 'ok'}), ToolCall('done', {'result': 'again'})),
    (ToolCall('click', {'target': 'A'}), ToolCall('unknown', {})),
    (ToolCall('click', {'target': 'A'}), ToolCall('type', {'target': 'B'})),
    (ToolCall('click', {'target': 'A'}), ToolCall('wait_for', {'text': 'A', 'ref': 'B'})),
])
async def test_invalid_batch_preflight_dispatches_zero(calls):
    runner = Runner(make_llm([batch(*calls)]), FakePage(['page']), Trace())
    runner._dispatch = AsyncMock()
    result = await runner.run('goal')
    assert result.outcome == 'action_error' and result.tokens == 10
    runner._dispatch.assert_not_awaited()
    assert results(runner) == []


async def test_invalid_second_json_dispatches_zero():
    runner = Runner(make_llm([batch(ToolCall('click', {'target': 'A'}),
                                  ToolCall('read', {'bad': float('nan')}))]),
                    FakePage(['page']), Trace())
    runner._dispatch = AsyncMock()
    with pytest.raises(ValueError, match='JSON'):
        await runner.run('goal')
    runner._dispatch.assert_not_awaited()


@pytest.mark.parametrize('name', ['click', 'type', 'select', 'hover'])
@pytest.mark.parametrize('timing', ['dispatch', 'snapshot', 'payload'])
@pytest.mark.parametrize('position', [0, 1])
async def test_batch_uncertain_mutation_never_runs_tail(name, timing, position):
    page = FakePage(['page'])
    attempted = []
    original_snapshot, original_payload = page.snapshot, page.payload

    async def mutate(*args):
        attempted.append(name)
        if timing == 'dispatch':
            raise ConnectionError('lost response')

    async def snapshot():
        if attempted and timing == 'snapshot':
            raise ConnectionError('lost observation')
        return await original_snapshot()

    def payload(version):
        if attempted and timing == 'payload':
            raise ConnectionError('lost observation')
        return original_payload(version)

    setattr(page, name, mutate)
    page.click = mutate if name == 'click' else AsyncMock()
    page.snapshot, page.payload = snapshot, payload
    args = {'target': 'Field'}
    if name == 'type':
        args['text'] = 'value'
    if name == 'select':
        args['value'] = 'choice'
    calls = ([ToolCall('read', {}, 'read')] if position else []) + [
        ToolCall(name, args, 'mutation'), ToolCall('click', {'target': 'Never'}, 'tail')]
    llm = make_llm([batch(*calls)])
    runner = Runner(llm, page, Trace())
    result = await runner.run('goal')
    assert result.outcome == 'ambiguous_action' and result.success is False
    assert attempted == [name] and llm.complete.await_count == 1
    assert len(results(runner)) == len(calls)
    assert 'NOT_EXECUTED' in results(runner)[-1]['content']
    if name != 'click':
        page.click.assert_not_awaited()


async def test_safe_error_skips_batch_tail_before_next_response():
    page = FakePage(['page'])
    page.read = AsyncMock(side_effect=GripError(BrowserError(
        ErrorType.ELEMENT_STALE, 'missing', 1, [RecoveryAction.RETRY])))
    page.click = AsyncMock()
    runner = Runner(make_llm([batch(ToolCall('read', {}, 'a'),
                                   ToolCall('click', {'target': 'Never'}, 'b')),
                             LLMResponse(None, ToolCall('done', {'result': 'ok'}, 'c'))]),
                    page, Trace())
    result = await runner.run('goal')
    assert result.success is True and result.model_calls == 2
    page.click.assert_not_awaited()
    assert [m['tool_call_id'] for m in results(runner)] == ['a', 'b']
    assert 'NOT_EXECUTED' in results(runner)[-1]['content']


async def test_oversized_batch_dispatches_zero():
    runner = Runner(make_llm([batch(*(ToolCall('read', {}, str(i)) for i in range(4)))]),
                    FakePage(['page']), Trace(), max_steps=3)
    runner._dispatch = AsyncMock()
    result = await runner.run('goal')
    assert result.outcome == 'step_limit' and result.model_calls == 1
    runner._dispatch.assert_not_awaited()


async def test_cancellation_matches_all_batch_results_and_propagates():
    page = FakePage(['page'])
    page.read = AsyncMock(side_effect=asyncio.CancelledError())
    runner = Runner(make_llm([batch(ToolCall('read', {}, 'a'),
                                   ToolCall('click', {'target': 'Never'}, 'b'))]), page, Trace())
    with pytest.raises(asyncio.CancelledError):
        await runner.run('goal')
    assert [m['tool_call_id'] for m in results(runner)] == ['a', 'b']
    assert 'CANCELLED' in results(runner)[0]['content']
    assert 'NOT_EXECUTED' in results(runner)[1]['content']


@pytest.mark.parametrize('metadata', [
    {'provider': 'unknown'},
    {'provider': 'gemini', 'content': {}},
    {'provider': 'anthropic', 'content': [{'type': 'text', 'text': 'missing call'}]},
])
async def test_invalid_replay_metadata_preflight_dispatches_zero(metadata):
    response = batch(ToolCall('click', {'target': 'A'}, 'native'))
    response.replay_metadata = metadata
    runner = Runner(make_llm([response]), FakePage(['page']), Trace())
    runner._dispatch = AsyncMock()
    result = await runner.run('goal')
    assert result.outcome == 'action_error' and result.tokens == 10
    runner._dispatch.assert_not_awaited()


async def test_mutated_conflicting_dto_dispatches_zero():
    response = batch(ToolCall('click', {'target': 'A'}, 'native'))
    response.tool_call = ToolCall('read', {})
    runner = Runner(make_llm([response]), FakePage(['page']), Trace())
    runner._dispatch = AsyncMock()
    result = await runner.run('goal')
    assert result.outcome == 'action_error'
    runner._dispatch.assert_not_awaited()


async def test_absent_ids_never_overwrite_later_native_id():
    response = batch(ToolCall('read', {}), ToolCall('read', {}),
                     ToolCall('snapshot', {}, 'grip_call_0_0'))
    runner = Runner(make_llm([response]), FakePage(['page']), Trace(), max_steps=3)
    result = await runner.run('goal')
    ids = [m['tool_call_id'] for m in results(runner)]
    assert len(ids) == len(set(ids)) == 3 and ids[-1] == 'grip_call_0_0'
    assert result.model_calls == 1 and result.outcome == 'step_limit'


async def test_remaining_budget_rejects_whole_later_batch():
    runner = Runner(make_llm([batch(ToolCall('read', {}, 'a'), ToolCall('read', {}, 'b')),
                             batch(ToolCall('read', {}, 'c'), ToolCall('read', {}, 'd'))]),
                    FakePage(['page']), Trace(), max_steps=3)
    runner._dispatch = AsyncMock(return_value='page')
    result = await runner.run('goal')
    assert result.outcome == 'step_limit' and result.model_calls == 2 and result.tokens == 20
    assert runner._dispatch.await_count == 2
    assert [m['tool_call_id'] for m in results(runner)] == ['a', 'b']


async def test_reused_id_from_skipped_batch_call_rejected():
    page = FakePage(['page'])
    page.read = AsyncMock(side_effect=GripError(BrowserError(
        ErrorType.ELEMENT_STALE, 'missing', 1, [RecoveryAction.RETRY])))
    runner = Runner(make_llm([batch(ToolCall('read', {}, 'a'),
                                   ToolCall('click', {'target': 'Never'}, 'reserved')),
                             batch(ToolCall('click', {'target': 'Never'}, 'reserved'))]),
                    page, Trace())
    page.click = AsyncMock()
    result = await runner.run('goal')
    assert result.outcome == 'action_error' and result.model_calls == 2
    page.click.assert_not_awaited()


@pytest.mark.parametrize('prefix', [False, True])
async def test_safe_error_matches_all_three_results_before_recovery(prefix):
    page = FakePage(['page'])
    error = GripError(BrowserError(ErrorType.ELEMENT_STALE, 'missing', 1,
                                  [RecoveryAction.RETRY]))
    page.read = AsyncMock(side_effect=[await page.read(), error] if prefix else [error])
    page.click = AsyncMock()
    calls = ((ToolCall('read', {}, 'first'), ToolCall('read', {}, 'failed'),
              ToolCall('click', {'target': 'Never'}, 'last')) if prefix else
             (ToolCall('read', {}, 'failed'), ToolCall('click', {'target': 'Never'}, 'middle'),
              ToolCall('click', {'target': 'Never'}, 'last')))
    runner = Runner(make_llm([batch(*calls),
                             LLMResponse(None, ToolCall('done', {'result': 'recovered'}))]),
                    page, Trace())
    result = await runner.run('goal')
    assert result.success is True and result.model_calls == 2
    assert page.read.await_count == (2 if prefix else 1)
    page.click.assert_not_awaited()
    assert [m['tool_call_id'] for m in results(runner)] == [c.id for c in calls]
    skipped = [m for m in results(runner) if 'NOT_EXECUTED' in m['content']]
    assert len(skipped) == (1 if prefix else 2)


@pytest.mark.parametrize('content', [{'bad': 'text'}, ['text'], 1, True])
async def test_invalid_assistant_content_rejected_before_batch_dispatch(content):
    response = batch(ToolCall('click', {'target': 'Never'}, 'a'),
                     ToolCall('done', {'result': 'false success'}, 'b'))
    response.content = content
    runner = Runner(make_llm([response]), FakePage(['page']), Trace())
    runner._dispatch = AsyncMock()
    result = await runner.run('goal')
    assert result.outcome == 'action_error' and result.tokens == 10 and result.model_calls == 1
    runner._dispatch.assert_not_awaited()
    assert results(runner) == []
