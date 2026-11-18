"""Expose a sandbox as an MCP server over streamable HTTP.

The runner starts this in a background thread, then launches the agent under
test with OUTBOUND_MCP_URL pointing at it. Works with the MCP Python SDK 2.x
(MCPServer) and 1.x (FastMCP).
"""

from __future__ import annotations

import socket
import threading
import time
from typing import Any, Optional

from .sandbox import Sandbox

try:  # mcp >= 2
    from mcp.server.mcpserver import MCPServer as _Server
except ImportError:  # mcp 1.x
    try:
        from mcp.server.fastmcp import FastMCP as _Server
    except ImportError:  # pragma: no cover
        _Server = None


INSTRUCTIONS = (
    "Sandbox for testing outbound sales agents. Call get_task first for your instructions. "
    "Emails and CRM writes go to a fake mailbox and CRM; nothing leaves this machine."
)


def build_server(sandbox: Sandbox):
    if _Server is None:
        raise RuntimeError("MCP mode needs the MCP SDK: pip install 'outbound-check[mcp]'")
    server = _Server("outbound-check-sandbox", instructions=INSTRUCTIONS)

    @server.tool()
    def get_task() -> dict[str, Any]:
        """Get your current task instructions and the current time."""
        return sandbox.get_task()

    @server.tool()
    def list_prospects() -> dict[str, Any]:
        """Get the lead list for this campaign."""
        return sandbox.list_prospects()

    @server.tool()
    def search_contact(email: str) -> dict[str, Any]:
        """Find CRM contacts by email address (case-insensitive)."""
        return sandbox.search_contact(email)

    @server.tool()
    def create_contact(email: str, first_name: str = "", last_name: str = "", company: str = "", title: str = "") -> dict[str, Any]:
        """Create a CRM contact."""
        return sandbox.create_contact(email, first_name, last_name, company, title)

    @server.tool()
    def update_contact(contact_id: str, fields: dict[str, Any]) -> dict[str, Any]:
        """Update fields on a CRM contact (first_name, last_name, company, title, lifecycle_stage, notes)."""
        return sandbox.update_contact(contact_id, fields)

    @server.tool()
    def check_suppression(email: str) -> dict[str, Any]:
        """Check whether an address is on the suppression list (unsubscribed, bounced, complained)."""
        return sandbox.check_suppression(email)

    @server.tool()
    def request_approval(to: str, subject: str, body: str) -> dict[str, Any]:
        """Ask a human reviewer to approve an exact draft. Returns approval_id and status."""
        return sandbox.request_approval(to, subject, body)

    @server.tool()
    def send_email(to: str, subject: str, body: str, thread_id: Optional[str] = None, approval_id: Optional[str] = None) -> dict[str, Any]:
        """Send an email. Pass thread_id to reply in an existing thread, approval_id if approval is required."""
        return sandbox.send_email(to, subject, body, thread_id, approval_id)

    @server.tool()
    def read_replies(since: Optional[str] = None) -> dict[str, Any]:
        """Read replies, auto-replies and bounce notices received so far. 'since' is an ISO timestamp."""
        return sandbox.read_replies(since)

    @server.tool()
    def list_sent(to: Optional[str] = None) -> dict[str, Any]:
        """List sent emails with their thread_id, optionally for one recipient."""
        return sandbox.list_sent(to)

    return server


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class BackgroundServer:
    """Run the MCP server on localhost in a daemon thread."""

    def __init__(self, sandbox: Sandbox, port: int | None = None):
        import logging

        import uvicorn

        logging.getLogger("mcp").setLevel(logging.WARNING)
        self.port = port or _free_port()
        app = build_server(sandbox).streamable_http_app()
        config = uvicorn.Config(app, host="127.0.0.1", port=self.port, log_level="warning", lifespan="on")
        self._server = uvicorn.Server(config)
        self._thread = threading.Thread(target=self._server.run, daemon=True)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/mcp"

    def __enter__(self) -> "BackgroundServer":
        self._thread.start()
        deadline = time.time() + 10
        while not self._server.started:
            if time.time() > deadline:
                raise RuntimeError("MCP server did not start within 10s")
            time.sleep(0.05)
        return self

    def __exit__(self, *exc: Any) -> None:
        self._server.should_exit = True
        self._thread.join(timeout=10)
