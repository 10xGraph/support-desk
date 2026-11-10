"""The support agent's MCP calls, end to end over HTTP, without Postgres.

Real 10xGraph ToolNode with mcp_auth (graph/support_tools.py) -> real demo_server MCP app with
its token verifier. Only the database pool is fake; it records which company each query used.
"""

import socket
import threading
import time
from collections.abc import Iterator
from decimal import Decimal

import pytest
import uvicorn
from fastapi import FastAPI
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport
from tenxgraph.core import AgentState, ToolNode
from tenxgraph.core.authz import Identity, Reach
from tenxgraph.utils.callbacks import CallbackManager

from demo_server import db
from demo_server.main import mcp_app
from graph.support_tools import demo_server_auth


class FakePool:
    def __init__(self) -> None:
        self.queries: list[tuple] = []

    async def fetchrow(self, sql: str, *args):
        self.queries.append(args)
        if args == ("acme", "A-1002"):
            return {
                "item": "27-inch monitor",
                "total": Decimal("250.00"),
                "status": "delivered",
                "refund_amount": None,
                "refund_status": None,
            }
        return None


@pytest.fixture
def server(monkeypatch) -> Iterator[tuple[str, FakePool]]:
    pool = FakePool()
    monkeypatch.setattr(db, "pool", pool)
    app = FastAPI(lifespan=lambda app: mcp_app.lifespan(app))
    app.mount("/mcp", mcp_app)
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    uv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=uv.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not uv.started:
        if time.monotonic() > deadline:
            raise RuntimeError("uvicorn did not start")
        time.sleep(0.02)
    yield f"http://127.0.0.1:{port}/mcp/", pool
    uv.should_exit = True
    thread.join(timeout=10)


def run_config(user_id: str, org_id: str) -> dict:
    identity = Identity(
        user_id=user_id, tenant={"org_id": org_id}, roles=["member"], reach=Reach.OWN
    )
    return {"thread_id": "t1", "run_id": "r1", "user_id": user_id, "user": identity}


async def lookup(url: str, config: dict, order_id: str) -> str:
    node = ToolNode([], client=Client(StreamableHttpTransport(url)), mcp_auth=demo_server_auth)
    tools = await node.all_tools(config=config)
    assert "lookup_order" in {t["function"]["name"] for t in tools}
    message = await node.invoke(
        "lookup_order", {"order_id": order_id}, "call-1", config, AgentState(), CallbackManager()
    )
    return message.text()


async def test_customer_reaches_own_company_orders(server) -> None:
    url, pool = server
    text = await lookup(url, run_config("alice", "acme"), "A-1002")
    assert "27-inch monitor" in text
    assert pool.queries == [("acme", "A-1002")]


async def test_company_comes_from_the_token_not_the_arguments(server) -> None:
    url, pool = server
    text = await lookup(url, run_config("bob", "globex"), "A-1002")
    assert "not found" in text
    assert pool.queries == [("globex", "A-1002")]


async def test_without_a_customer_tools_list_but_refuse(server) -> None:
    url, pool = server
    text = await lookup(url, {"thread_id": "t1", "run_id": "r1"}, "A-1002")
    assert "27-inch monitor" not in text
    assert pool.queries == []
