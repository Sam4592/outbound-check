"""The careful agent, run as a separate process that talks to the sandbox over MCP.

This is how a real agent plugs in: it reads OUTBOUND_MCP_URL and OUTBOUND_TASK
from the environment and uses the sandbox tools like any other MCP server.

    outbound-check run --agent-cmd "python examples/mcp_agent.py"

Needs the MCP Python SDK 2.x (pip install 'mcp>=2').
"""

import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import careful_agent  # noqa: E402

from mcp.client.client import Client  # noqa: E402


class McpTools:
    """Sync facade over an async MCP client, so the same agent logic runs in both modes.

    The agent logic runs in a worker thread; each tool call is scheduled back
    onto the event loop that owns the MCP session.
    """

    def __init__(self, client, loop):
        self._client = client
        self._loop = loop

    def __getattr__(self, name):
        def call(*args, **kwargs):
            if args:
                raise TypeError("MCP tools take keyword arguments only")
            future = asyncio.run_coroutine_threadsafe(self._client.call_tool(name, kwargs), self._loop)
            result = future.result(timeout=60)
            if result.is_error:
                raise RuntimeError(f"{name} failed: {result.content}")
            if result.structured_content is not None:
                data = result.structured_content
                return data["result"] if set(data) == {"result"} else data
            return json.loads(result.content[0].text)
        return call


class KwargTools:
    """careful_agent passes some arguments positionally; map them to names for MCP."""

    SIGNATURES = {
        "check_suppression": ["email"],
        "search_contact": ["email"],
        "create_contact": ["email", "first_name", "last_name", "company", "title"],
        "request_approval": ["to", "subject", "body"],
        "send_email": ["to", "subject", "body"],
    }

    def __init__(self, tools):
        self._tools = tools

    def __getattr__(self, name):
        fn = getattr(self._tools, name)
        names = self.SIGNATURES.get(name, [])

        def call(*args, **kwargs):
            kwargs.update(zip(names, args))
            return fn(**{k: v for k, v in kwargs.items() if v is not None})
        return call


async def main():
    async with Client(os.environ["OUTBOUND_MCP_URL"]) as client:
        tools = McpTools(client, asyncio.get_running_loop())

        def work():
            task = os.environ.get("OUTBOUND_TASK") or tools.get_task()["task"]
            careful_agent.run(task, KwargTools(tools))

        await asyncio.to_thread(work)


if __name__ == "__main__":
    asyncio.run(main())
