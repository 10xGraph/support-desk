# demo_server

A demo "company system" next to the support agent: orders, refunds and tickets in Postgres
(schema `demo`, same database as the 10xGraph API). A REST API for people and an MCP server
for the agent, both checked with the API's JWTs.

| File | What |
|---|---|
| `main.py` | the FastAPI `app`; startup opens the pool and runs `schema.sql`; MCP mounted at `/mcp/` |
| `db.py` | asyncpg pool |
| `schema.sql` | tables and the dummy orders (acme, globex) |
| `auth.py` | `decode_token`, `current_user`, `staff_user`, the MCP token verifier |
| `routes.py` | REST endpoints |
| `mcp_server.py` | MCP tools |

## Run

```bash
export DATABASE_URL=postgresql://tenxgraph:tenxgraph@127.0.0.1:5433/tenxgraph
export JWT_SECRET_KEY=...   # same as the API
uvicorn demo_server.main:app --port 8100
```

In Docker Compose it runs as the `demo-server` service.

## REST

Bearer token from `deploy/scripts/make_token.py` (claims `user_id`, `name`, `roles`, `org_id`, `exp`).
Every query is limited to the token's `org_id`.

| Endpoint | Who |
|---|---|
| `GET /ping` | anyone |
| `GET /v1/orders` | any user |
| `GET /v1/refunds?status=pending` | staff (support, org_admin, admin) |
| `POST /v1/refunds/{id}/approve`, `POST /v1/refunds/{id}/reject` | staff; pending refunds only, not ones they requested |
| `GET /v1/tickets` | staff |

## MCP (`/mcp/`)

Only the support agent's own tokens: audience `demo-mcp`, signed with the same secret. The agent
signs one per call through 10xGraph's `ToolNode(mcp_auth=...)` (`graph/support_tools.py`), valid
for 60 seconds, naming the customer (`user_id`, `org_id`) and itself as the actor
(`act.sub = "support-agent"`). Tools take the customer from that verified token. A token with
only the agent (role `service`) can list tools but not use them. A user's own token has no
audience and is refused here; an agent token has one and is refused on the REST API. Anyone
holding `JWT_SECRET_KEY` can sign these tokens, so keep `/mcp` on the internal network.

Tools: `lookup_order(order_id)`, `refund_order(order_id, amount, reason)` (up to $100 issued at
once, more waits for staff; one refund per order), `create_ticket(summary, needs_human)`.

## Tests

```bash
.venv/bin/python -m pytest demo_server/tests -p no:cacheprovider --no-cov
```

`test_api.py` needs a Postgres it may wipe the `demo` schema of:
`TEST_DATABASE_URL=postgresql://tenxgraph:tenxgraph@127.0.0.1:5433/tenxgraph`.
