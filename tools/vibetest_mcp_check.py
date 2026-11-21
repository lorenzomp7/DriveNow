"""Verify the real Vibetest MCP interface and credential gate without AI calls."""
import asyncio
from datetime import timedelta
import os
from pathlib import Path
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parents[1]


async def main():
    # Never inherit the credential in this no-cost contract check.
    env = {key: value for key, value in os.environ.items() if key != 'GOOGLE_API_KEY'}
    params = StdioServerParameters(command=sys.executable, args=[str(ROOT/'tools/vibetest_mcp.py')], cwd=str(ROOT), env=env)
    async with stdio_client(params) as (reader, writer):
        async with ClientSession(reader, writer, read_timeout_seconds=timedelta(seconds=120)) as client:
            await client.initialize()
            names = {tool.name for tool in (await client.list_tools()).tools}
            assert {'installation_status','test_drivenow'} <= names
            installation = await client.call_tool('installation_status', {})
            assert not installation.isError, installation
            blocked = await client.call_tool('test_drivenow', {'model':'credential-gate-check','timeout_seconds':30})
            assert blocked.isError, 'Missing Google credential did not prevent AI execution'
    print('VIBETEST_MCP_OK: installation tool and credential gate verified; AI calls: 0')


if __name__ == '__main__':
    asyncio.run(main())
