from types import SimpleNamespace
import pytest
from tools.container_use import extract_verified
from tools.container_use_smoke import result_text, environment_id


def test_bad_download_is_rejected_before_installation(tmp_path):
    archive = tmp_path / 'download.tar.gz'
    archive.write_bytes(b'incomplete or tampered archive')
    target = tmp_path / 'container-use'
    with pytest.raises(ValueError, match='SHA-256'):
        extract_verified(archive, '0' * 64, target)
    assert not target.exists()


def test_mcp_error_is_not_treated_as_success():
    with pytest.raises(RuntimeError, match='MCP tool failed'):
        result_text(SimpleNamespace(isError=True, content=[]))


def test_environment_response_must_contain_an_id():
    assert environment_id('{"id":"gentle-fox"}') == 'gentle-fox'
    with pytest.raises(ValueError, match='environment ID'):
        environment_id('{"title":"no environment"}')
