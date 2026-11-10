"""End-to-end against a real Postgres. Wipes the `demo` schema of TEST_DATABASE_URL."""

import asyncio
import os
from http import HTTPStatus

import asyncpg
import pytest
from fastapi.testclient import TestClient

from demo_server.main import app

from .conftest import make_token


DB_URL = os.getenv("TEST_DATABASE_URL")
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not DB_URL, reason="TEST_DATABASE_URL is not set"),
]

MCP_HEADERS = {"Accept": "application/json, text/event-stream"}


def auth(**kwargs):
    return {"Authorization": f"Bearer {make_token(**kwargs)}"}


async def drop_schema():
    conn = await asyncpg.connect(DB_URL)
    await conn.execute("DROP SCHEMA IF EXISTS demo CASCADE")
    await conn.close()


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", DB_URL)
    asyncio.run(drop_schema())
    with TestClient(app) as c:
        yield c


def call_tool(client, name, arguments, org_id="acme", user_id="alice"):
    body = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": name,
            "arguments": arguments,
            "_meta": {"user": {"user_id": user_id, "tenant": {"org_id": org_id}}},
        },
    }
    headers = {**MCP_HEADERS, **auth(user_id="support-agent", roles=["service"], org_id=None)}
    r = client.post("/mcp/", json=body, headers=headers)
    assert r.status_code == HTTPStatus.OK, r.text
    return r.json()["result"]["content"][0]["text"]


def test_orders_scoped_by_org(client):
    assert client.get("/v1/orders").status_code == HTTPStatus.UNAUTHORIZED
    acme = client.get("/v1/orders", headers=auth()).json()
    assert [o["order_id"] for o in acme] == ["A-1001", "A-1002", "A-1003"]
    globex = client.get("/v1/orders", headers=auth(org_id="globex")).json()
    assert [o["order_id"] for o in globex] == ["G-2001", "G-2002"]


def test_refund_flow(client):
    assert "issued" in call_tool(
        client, "refund_order", {"order_id": "A-1001", "amount": 45, "reason": "broken"}
    )
    assert "pending" in call_tool(
        client, "refund_order", {"order_id": "A-1002", "amount": 250, "reason": "dead pixels"}
    )
    assert "already has a refund" in call_tool(
        client, "refund_order", {"order_id": "A-1001", "amount": 10, "reason": "again"}
    )
    assert "at most the order total" in call_tool(
        client, "refund_order", {"order_id": "A-1003", "amount": 100, "reason": "too much"}
    )

    staff = auth(user_id="sam", roles=["support"])
    pending = client.get("/v1/refunds?status=pending", headers=staff).json()
    assert [r["order_id"] for r in pending] == ["A-1002"]
    refund_id = pending[0]["id"]

    assert client.get("/v1/refunds", headers=auth()).status_code == HTTPStatus.FORBIDDEN
    other_org = auth(user_id="gina", roles=["support"], org_id="globex")
    approve = f"/v1/refunds/{refund_id}/approve"
    assert client.post(approve, headers=other_org).status_code == HTTPStatus.NOT_FOUND
    requester = auth(user_id="alice", roles=["support"])  # requested it via the agent
    assert client.post(approve, headers=requester).status_code == HTTPStatus.FORBIDDEN

    r = client.post(approve, headers=staff)
    assert r.status_code == HTTPStatus.OK
    assert r.json()["status"] == "issued"
    assert r.json()["decided_by"] == "sam"
    reject = f"/v1/refunds/{refund_id}/reject"
    assert client.post(reject, headers=staff).status_code == HTTPStatus.NOT_FOUND


def test_other_org_order_not_found(client):
    text = call_tool(client, "lookup_order", {"order_id": "G-2001"}, org_id="acme")
    assert text == "Order G-2001 not found."
    assert "not found" in call_tool(
        client, "refund_order", {"order_id": "G-2001", "amount": 5, "reason": "x"}, org_id="acme"
    )
    assert "Mechanical keyboard" in call_tool(
        client, "lookup_order", {"order_id": "G-2001"}, org_id="globex"
    )


def test_ticket(client):
    text = call_tool(client, "create_ticket", {"summary": "Wants a person", "needs_human": True})
    assert text == "Ticket ACME-1001 created."
    tickets = client.get("/v1/tickets", headers=auth(user_id="sam", roles=["support"])).json()
    assert tickets[0]["needs_human"] is True


def test_mcp_rejects_non_service_token(client):
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
    r = client.post("/mcp/", json=body, headers={**MCP_HEADERS, **auth(roles=["admin"])})
    assert r.status_code == HTTPStatus.UNAUTHORIZED
    r = client.post("/mcp/", json=body, headers=MCP_HEADERS)
    assert r.status_code == HTTPStatus.UNAUTHORIZED
