# phoenix-demo

A multi-tenant support desk built on 10xGraph, with the full stack in Docker: API, demo_server
(company data), Postgres, Redis, RabbitMQ (events), Phoenix (AI traces), Prometheus and Grafana
(metrics). For now the image installs `10xgraph` and `10xgraph-api` from the local checkouts
`../agentflow` and `../agentflow-api` (see `Dockerfile`). Tenants are `acme` and `globex`
(token claim `org_id`).

## How it works

One ReAct support agent (`graph/agent.py`): a Gemini `Agent` node and a `ToolNode` in a loop. Its
tools come from the `demo_server` MCP server: `lookup_order`, `refund_order` and `create_ticket`.
`demo_server/` holds the company data and business rules (orders, refunds, tickets) in the
Postgres schema `demo`, and exposes a REST API and the MCP endpoint, both checked against the
same JWT secret as the API. For every MCP call the agent signs a 60-second token
(10xGraph `mcp_auth`, audience `demo-mcp`) that names the signed-in customer and the agent as
the actor, so demo_server decides whose data a tool may touch from a verified token. The
customer's own API token is never forwarded. See
`demo_server/README.md` for its details.

Refunds up to $100 go through at once. Larger ones are stored as pending until staff approve them
(see "Approving a refund").

Local testing setup: there is no reverse proxy yet, and every port binds to `127.0.0.1`.

## Start

1. Create `.env` and fill in the secrets (see `.env.example` for every variable):

   ```bash
   cp .env.example .env
   .venv/bin/python deploy/scripts/make_secret.py   # writes JWT_SECRET_KEY and JWT_ALGORITHM
   # then set GOOGLE_API_KEY, POSTGRES_PASSWORD, RABBITMQ_PASSWORD, GRAFANA_ADMIN_PASSWORD,
   # PGADMIN_PASSWORD,
   # and the same passwords in DATABASE_URL and BROKER_URL
   ```

2. Start everything:

   ```bash
   docker compose up --build
   ```

   Postgres starts, `seed` loads the knowledge base and exits, then the API starts on
   http://localhost:8000 (`curl http://localhost:8000/ping`).

3. Make a token per user, role and tenant (prints only the token; reads `.env`):

   ```bash
   TOKEN=$(.venv/bin/python deploy/scripts/make_token.py alice --name "Alice Chen" --role member --org acme)
   curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/v1/me   # shows role, tenant, reach
   ```

   | Role | Reach | Can do |
   |---|---|---|
   | `member` | own threads | chat, own threads, files |
   | `support` | whole tenant | read tenant threads, invoke and stop runs, approve refunds on demo_server (see below) |
   | `org_admin` | whole tenant | support, plus delete, graph read and fix |
   | `admin` | all tenants | everything |

4. Playground: open https://play.10xgraph.com, set the API URL to `http://localhost:8000`, paste
   a token and chat.

5. Evals run on the host against the stack (they use the `127.0.0.1` URLs in `.env`):

   ```bash
   .venv/bin/10xgraph eval evals/support_agent_eval.py
   ```

## Approving a refund

Refunds above $100 stay pending on demo_server; the agent tells the customer they wait for staff.
A user with role `support`, `org_admin` or `admin` approves one with the same kind of token.
demo_server listens on `127.0.0.1:8100`:

```bash
STAFF_TOKEN=$(.venv/bin/python deploy/scripts/make_token.py sam --name "Sam Lee" --role support --org acme)
curl -H "Authorization: Bearer $STAFF_TOKEN" "http://127.0.0.1:8100/v1/refunds?status=pending"
curl -X POST -H "Authorization: Bearer $STAFF_TOKEN" http://127.0.0.1:8100/v1/refunds/<refund_id>/approve
```

The route, the tenant check and the other endpoints are documented in `demo_server/README.md`.

## Background jobs

The `worker` and `scheduler` services run the API image with TaskIQ over RabbitMQ (status and
results in Redis); `worker` in `10xgraph.json` lists the task modules (`worker/tasks.py`). The
image has no `10xgraph` command, so they run `taskiq worker` and `taskiq scheduler`, which is what
`10xgraph worker` and `10xgraph scheduler` run. Run exactly one scheduler.

```bash
curl -X POST http://localhost:8000/v1/tasks/summarize_thread \
  -H "Authorization: Bearer $TOKEN" -H 'content-type: application/json' \
  -d '{"kwargs": {"thread_id": "<thread id>"}}'
docker compose logs -f worker
```

## Dashboards

| What | URL | Login |
|---|---|---|
| Phoenix (AI traces), project `support-desk` | http://127.0.0.1:6006 | none (auth off locally) |
| Grafana, dashboard "10xGraph" | http://127.0.0.1:3001 | `admin` / `GRAFANA_ADMIN_PASSWORD` |
| RabbitMQ management, queue `tenxgraph.events.demo` | http://127.0.0.1:15672 | `tenxgraph` / `RABBITMQ_PASSWORD` |
| pgAdmin, server `support-desk` | http://127.0.0.1:5050 | `PGADMIN_EMAIL` / `PGADMIN_PASSWORD`; then `POSTGRES_PASSWORD` for the database |
| Prometheus | http://127.0.0.1:9090 | none; type `{job="10xgraph-api"}` in the Graph tab to list API metrics |

Audit events and JSON application logs go to the API container's stdout:
`docker compose logs api | grep tenxgraph_api.audit`.

Passwords in `.env` apply when a volume is first created. After changing one, run
`docker compose down -v` (this deletes all data) or change it inside the service too.

## Reset

```bash
docker compose down -v
```

removes the containers and all volumes (threads, traces, queue messages, metrics).

## How events and traces are wired

`graph/agent.py` passes a `RabbitMQPublisher` (kind `events`) to the `StateGraph` (`publisher=...`). When the API
starts it adds the Phoenix publisher (kind `observability`, from `observability` in
`10xgraph.json`) next to it, so the graph runs with one `CompositePublisher`. Metrics come from
the `metrics` block and go straight to Prometheus.
