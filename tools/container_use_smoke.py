"""Use the real MCP server to run DriveNow tests in a disposable environment."""
import argparse
import asyncio
from datetime import timedelta
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.container_use import BINARY, doctor


def result_text(result):
    if result.isError:
        raise RuntimeError('MCP tool failed: ' + '\n'.join(getattr(c, 'text', '') for c in result.content))
    return '\n'.join(getattr(c, 'text', '') for c in result.content)


def environment_id(text):
    obj, _ = json.JSONDecoder().raw_decode(text.lstrip())
    if not isinstance(obj.get('id'), str) or not obj['id']:
        raise ValueError('MCP response has no environment ID')
    return obj['id']


async def exercise(source):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    env = {key: value for key, value in os.environ.items()
           if key in {'DOCKER_HOST', 'DOCKER_CONTEXT', 'DOCKER_CONFIG', 'DOCKER_TLS_VERIFY',
                      'DOCKER_CERT_PATH', '_EXPERIMENTAL_DAGGER_CLI_BIN'}}
    if os.name != 'nt':
        env['CONTAINER_USE_STDERR_FILE'] = '/dev/stderr'
    params = StdioServerParameters(command=str(BINARY), args=['stdio'], cwd=str(source), env=env)
    async with stdio_client(params) as (reader, writer):
        async with ClientSession(reader, writer, read_timeout_seconds=timedelta(minutes=12)) as session:
            await session.initialize()
            tools = {tool.name for tool in (await session.list_tools()).tools}
            if not {'environment_create', 'environment_run_cmd'} <= tools:
                raise RuntimeError('Required container-use MCP tools are missing')
            created = await session.call_tool('environment_create', {
                'environment_source': str(source), 'title': 'DriveNow isolated verification',
                'from_git_ref': 'HEAD', 'explanation': 'Verify DriveNow in an isolated container'})
            env = environment_id(result_text(created))
            try:
                result = await session.call_tool('environment_run_cmd', {
                    'environment_source': str(source), 'environment_id': env,
                    'command': 'python -m pytest -q && python tools/container_demo_check.py',
                    'explanation': 'Run engine tests and HTTP demo checks in the container'})
                output = result_text(result)
                if 'DRIVENOW_CONTAINER_DEMO_OK' not in output:
                    raise RuntimeError('Container did not return the demo verification marker')
                print(output)
                print(json.dumps({'status': 'passed', 'environment_id': env, 'ai_agents_launched': 0}))
            finally:
                # Delete only this disposable environment, never all user environments.
                subprocess.run([str(BINARY), 'delete', env], cwd=source, check=True, timeout=120)


def prepare_source(root, source):
    subprocess.run(['git', 'clone', '--no-hardlinks', str(root), str(source)], check=True)
    # v0.4.2 accepts a local repository with no origin, but rejects an origin
    # whose URL is a plain filesystem path (as produced by this local clone).
    subprocess.run(['git', 'remote', 'remove', 'origin'], cwd=source, check=True)
    subprocess.run(['git', 'config', 'user.name', 'DriveNow container check'], cwd=source, check=True)
    subprocess.run(['git', 'config', 'user.email', 'container-check@example.invalid'], cwd=source, check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    if doctor() != 0:
        print('Docker and the project-local binary are required; no container test ran.', file=sys.stderr)
        return 2
    with tempfile.TemporaryDirectory(prefix='drivenow_container_') as directory:
        source = Path(directory) / 'source'
        # This clone receives only the committed source, with no host secrets.
        prepare_source(ROOT, source)
        asyncio.run(asyncio.wait_for(exercise(source), timeout=900))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
