import json
import pytest
from tools import devtools


def test_vibetest_status_is_blocked_without_credentials(monkeypatch):
    monkeypatch.delenv('GOOGLE_API_KEY', raising=False)
    monkeypatch.delenv('VIBETEST_MODEL', raising=False)
    report = devtools.status()['vibetest']
    assert report['needs'] == ['GOOGLE_API_KEY', 'VIBETEST_MODEL']
    assert report['test_executed'] is False


def test_no_silent_run_if_environment_is_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(devtools, 'ROOT', tmp_path)
    with pytest.raises(RuntimeError, match='setup darts'):
        devtools.tool_command('darts')


def test_mcp_config_keeps_keys_out_and_routes_to_actual_tools():
    config = devtools.mcp_config()
    assert set(config['mcpServers']) == {'playwriter','container','vibetest'}
    assert 'GOOGLE_API_KEY' not in json.dumps(config)
    assert config['mcpServers']['vibetest']['args'][-2:] == ['mcp','vibetest']


def test_workflow_provenance_matches_manifest():
    assert devtools.validate_skills() == 7


def test_setup_without_names_installs_all_profiles(monkeypatch):
    called = []
    monkeypatch.setattr(devtools, 'setup', called.append)
    assert devtools.main(['setup']) == 0
    assert called == devtools.NAMES
