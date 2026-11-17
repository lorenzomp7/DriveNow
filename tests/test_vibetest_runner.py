import asyncio
from types import SimpleNamespace

import pytest

from tools.vibetest_drive import run_test, validate_target


def test_rejects_non_http_target():
    with pytest.raises(ValueError, match='HTTP'):
        validate_target('file:///etc/passwd')


def test_missing_key_stops_before_loading_backend(monkeypatch):
    monkeypatch.delenv('GOOGLE_API_KEY', raising=False)
    with pytest.raises(ValueError, match='GOOGLE_API_KEY'):
        asyncio.run(run_test('http://127.0.0.1:8000', 'chosen-model', 30))


def backend_with_result(result):
    backend = SimpleNamespace(ChatGoogle=lambda **kw: kw, scout_page=None, _test_results={})

    async def run_pool(url, num_agents, headless):
        assert num_agents == 1 and headless
        tasks = await backend.scout_page(url)
        assert 'DriveNow' in tasks[0] and url in tasks[0]
        assert backend.ChatGoogle(model='retired-model')['model'] == 'chosen-model'
        backend._test_results['run-1'] = {'results': result}
        return 'run-1'

    backend.run_pool = run_pool
    return backend


@pytest.mark.parametrize('results', [[], [{'status': 'error', 'error': 'model unavailable'}],
                                    [{'status': 'success', 'result': 'None'}]])
def test_empty_or_failed_agents_never_count_as_completed(monkeypatch, results):
    monkeypatch.setenv('GOOGLE_API_KEY', 'test-only')
    backend = backend_with_result(results)
    original = backend.ChatGoogle
    report = asyncio.run(run_test('http://127.0.0.1:8000', 'chosen-model', 30, backend))
    assert report['execution_status'] == 'failed'
    assert backend.ChatGoogle is original and backend.scout_page is None


def test_success_preserves_findings_without_claiming_test_pass(monkeypatch):
    monkeypatch.setenv('GOOGLE_API_KEY', 'test-only')
    backend = backend_with_result([{'status': 'success', 'result': 'Zoom button is broken'}])
    report = asyncio.run(run_test('http://127.0.0.1:8000', 'chosen-model', 30, backend))
    assert report['execution_status'] == 'completed'
    assert report['review_required'] is True
    assert report['raw']['results'][0]['result'] == 'Zoom button is broken'
    assert 'test-only' not in str(report)


def test_real_backend_close_contract_is_restored_after_run(monkeypatch):
    monkeypatch.setenv('GOOGLE_API_KEY', 'test-only')
    backend = backend_with_result([{'status':'success', 'result':'Checked demo'}])
    class Session:
        killed = False
        async def kill(self):
            Session.killed = True
    backend.BrowserSession = Session
    original_pool = backend.run_pool
    async def pool(*args, **kwargs):
        await backend.BrowserSession().aclose()
        return await original_pool(*args, **kwargs)
    backend.run_pool = pool
    result = asyncio.run(run_test('http://127.0.0.1:8000', 'chosen-model', 30, backend))
    assert result['execution_status'] == 'completed'
    assert Session.killed and not hasattr(Session, 'aclose')
