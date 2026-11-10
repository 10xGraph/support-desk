"""REST API. The org always comes from the verified token, never from the request."""

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException

from demo_server import db
from demo_server.auth import current_user, staff_user


router = APIRouter()


@router.get("/ping")
async def ping() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/v1/orders")
async def list_orders(user: dict = Depends(current_user)) -> list[dict[str, Any]]:
    rows = await db.pool.fetch(
        "SELECT order_id, item, total, status FROM demo.orders WHERE org_id = $1"
        " ORDER BY order_id",
        user["org_id"],
    )
    return [dict(r) for r in rows]


@router.get("/v1/refunds")
async def list_refunds(
    status: Literal["issued", "pending", "rejected"] | None = None,
    user: dict = Depends(staff_user),
) -> list[dict[str, Any]]:
    rows = await db.pool.fetch(
        "SELECT * FROM demo.refunds WHERE org_id = $1 AND ($2::text IS NULL OR status = $2)"
        " ORDER BY id",
        user["org_id"],
        status,
    )
    return [dict(r) for r in rows]


async def decide_refund(refund_id: int, user: dict, status: str) -> dict[str, Any]:
    row = await db.pool.fetchrow(
        "UPDATE demo.refunds SET status = $3, decided_by = $4, decided_at = now()"
        " WHERE id = $1 AND org_id = $2 AND status = 'pending' AND requested_by <> $4"
        " RETURNING *",
        refund_id,
        user["org_id"],
        status,
        user["user_id"],
    )
    if row is not None:
        return dict(row)
    own = await db.pool.fetchval(
        "SELECT requested_by = $3 FROM demo.refunds"
        " WHERE id = $1 AND org_id = $2 AND status = 'pending'",
        refund_id,
        user["org_id"],
        user["user_id"],
    )
    if own:
        raise HTTPException(403, "You cannot decide a refund you requested.")
    raise HTTPException(404, "No pending refund with that id.")


@router.post("/v1/refunds/{refund_id}/approve")
async def approve_refund(refund_id: int, user: dict = Depends(staff_user)) -> dict[str, Any]:
    return await decide_refund(refund_id, user, "issued")


@router.post("/v1/refunds/{refund_id}/reject")
async def reject_refund(refund_id: int, user: dict = Depends(staff_user)) -> dict[str, Any]:
    return await decide_refund(refund_id, user, "rejected")


@router.get("/v1/tickets")
async def list_tickets(user: dict = Depends(staff_user)) -> list[dict[str, Any]]:
    rows = await db.pool.fetch(
        "SELECT * FROM demo.tickets WHERE org_id = $1 ORDER BY id", user["org_id"]
    )
    return [dict(r) for r in rows]
