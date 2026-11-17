"""Credential-gated MCP entry point for the project's executable Vibetest runner."""
import asyncio
import logging
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ['ANONYMIZED_TELEMETRY'] = 'false'
os.environ['BROWSER_USE_LOGGING_LEVEL'] = 'CRITICAL'
logging.disable(logging.CRITICAL)
from mcp.server.fastmcp import FastMCP
from tools.vibetest_drive import run_test, check_install
from tools.devtools import demo_url

mcp = FastMCP('DriveNow Vibetest')


@mcp.tool()
async def installation_status() -> dict:
    """Check installed dependencies without starting an AI test or spending API credit."""
    return await asyncio.to_thread(check_install)


@mcp.tool()
async def test_drivenow(model: str, timeout_seconds: int = 600) -> dict:
    """Explore a temporary DriveNow demo with one Vibetest agent. Requires GOOGLE_API_KEY.

    This makes Google model API calls; invoke only when the user requests AI QA.
    Findings always require human review; completed does not mean bug-free.
    """
    if not 30 <= timeout_seconds <= 900:
        raise ValueError('timeout_seconds must be in 30..900')
    if not os.environ.get('GOOGLE_API_KEY'):
        raise ValueError('GOOGLE_API_KEY is required; no AI test was started')
    async with test_lock:
        with demo_url() as url:
            return await run_test(url, model, timeout_seconds)


test_lock = asyncio.Lock()
if __name__ == '__main__':
    mcp.run()
