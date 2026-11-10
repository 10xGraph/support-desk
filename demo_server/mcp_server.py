"""MCP server for the support agent: lookup_order, refund_order, create_ticket."""

from decimal import Decimal

import asyncpg
from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.dependencies import get_access_token

from demo_server import db
from demo_server.auth import AgentTokenVerifier


AUTO_REFUND_LIMIT = Decimal("100.00")

mcp = FastMCP("support-desk-systems", auth=AgentTokenVerifier(), mask_error_details=True)


def customer(ctx: Context) -> tuple[str, str]:
    """(org_id, user_id) of the customer the agent acts for, from the verified token.

    The agent signs one short-lived token per call (aud "demo-mcp") naming the customer and
    itself as the actor; AgentTokenVerifier checked it before this tool runs. A token without a
    customer (the agent fetching the tool list) can list tools but not use them.
    """
    token = get_access_token()
    claims = token.claims if token is not None else {}
    org_id, user_id = claims.get("org_id"), claims.get("user_id")
    if not claims.get("act") or not isinstance(org_id, str) or not org_id or not user_id:
        raise ToolError("No customer identity on this call.")
    return org_id, user_id


@mcp.tool
async def lookup_order(order_id: str, ctx: Context) -> str:
    """Look up one of the customer's orders by id (for example A-1002)."""
    org_id, _ = customer(ctx)
    order_id = order_id.strip().upper()
    row = await db.pool.fetchrow(
        "SELECT o.item, o.total, o.status, r.amount AS refund_amount, r.status AS refund_status"
        " FROM demo.orders o LEFT JOIN demo.refunds r"
        " ON r.org_id = o.org_id AND r.order_id = o.order_id"
        " WHERE o.org_id = $1 AND o.order_id = $2",
        org_id,
        order_id,
    )
    if row is None:
        return f"Order {order_id} not found."
    text = f"Order {order_id}: {row['item']}, ${row['total']}, {row['status']}."
    if row["refund_status"]:
        text += f" Refund of ${row['refund_amount']}: {row['refund_status']}."
    return text


@mcp.tool
async def refund_order(order_id: str, amount: float, reason: str, ctx: Context) -> str:
    """Refund one of the customer's orders. Up to $100.00 is refunded at once; larger
    amounts wait for staff approval. One refund per order."""
    org_id, user_id = customer(ctx)
    order_id = order_id.strip().upper()
    total = await db.pool.fetchval(
        "SELECT total FROM demo.orders WHERE org_id = $1 AND order_id = $2", org_id, order_id
    )
    if total is None:
        return f"Order {order_id} not found."
    amount = round(amount, 2)
    if not 0 < amount <= float(total):
        return f"The refund must be more than $0 and at most the order total, ${total}."
    value = Decimal(str(amount))
    status = "issued" if value <= AUTO_REFUND_LIMIT else "pending"
    try:
        refund_id = await db.pool.fetchval(
            "INSERT INTO demo.refunds (org_id, order_id, amount, reason, status, requested_by)"
            " VALUES ($1, $2, $3, $4, $5, $6) RETURNING id",
            org_id,
            order_id,
            value,
            reason,
            status,
            user_id,
        )
    except asyncpg.UniqueViolationError:
        return f"Order {order_id} already has a refund."
    if status == "issued":
        return f"Refund of ${value:.2f} for order {order_id} issued."
    return f"Refund of ${value:.2f} for order {order_id} is pending staff approval (#{refund_id})."


@mcp.tool
async def create_ticket(summary: str, ctx: Context, needs_human: bool = False) -> str:
    """Open a support ticket for the customer. Set needs_human when they ask for a person."""
    org_id, user_id = customer(ctx)
    ticket_id = await db.pool.fetchval(
        "INSERT INTO demo.tickets (org_id, user_id, summary, needs_human)"
        " VALUES ($1, $2, $3, $4) RETURNING id",
        org_id,
        user_id,
        summary,
        needs_human,
    )
    return f"Ticket {org_id.upper()}-{ticket_id} created."
