# phoenix-demo

A multi-tenant support desk built on 10xGraph, with the full stack in Docker: Caddy (TLS), API,
demo_server (company data), Postgres, Redis, RabbitMQ (events), Phoenix (AI traces), Prometheus and
Grafana (metrics). The
image installs `10xgraph` and `10xgraph-api` 1.0.0rc5 from PyPI. Tenants are `acme` and `globex`
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

Only Caddy (ports 80 and 443) is public. Everything else is on the internal Docker network.

## Start

1. Create `.env` from the template and fill in the two secrets (see `.env.example` for every variable):

   ```bash
   cp .env.example .env
   .venv/bin/python scripts/make_secret.py   # writes JWT_SECRET_KEY and JWT_ALGORITHM
   # then set GOOGLE_API_KEY in .env
   ```

2. Start everything:

   ```bash
   docker compose up --build
   ```

   For local scripts that need Postgres (`127.0.0.1:5433`), Redis (`6380`), RabbitMQ AMQP (`5672`)
   or the API directly (`8000`), add the dev override:

   ```bash
   docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d --build
   ```

3. Open https://localhost. Caddy signs a local certificate with its own CA, so the browser warns.
   Accept it, or trust the CA once:

   ```bash
   docker compose cp caddy:/data/caddy/pki/authorities/local/root.crt ./caddy-root.crt
   # then import caddy-root.crt into your browser or system trust store
   ```

   With `curl`, use `-k`: `curl -k https://localhost/ping`.

4. Make a token per user, role and tenant (prints only the token; reads `.env`):

   ```bash
   .venv/bin/python deploy/scripts/make_token.py alice --name "Alice Chen" --role member --org acme
   .venv/bin/python deploy/scripts/make_token.py sam --name "Sam Lee" --role support --org globex --ttl-hours 2
   curl -k -H "Authorization: Bearer $TOKEN" https://localhost/v1/me   # shows role, tenant, reach
   ```

   | Role | Reach | Can do |
   |---|---|---|
   | `member` | own threads | chat, own threads, files |
   | `support` | whole tenant | read tenant threads, invoke and stop runs, approve refunds on demo_server (see below) |
   | `org_admin` | whole tenant | support, plus delete, graph read and fix |
   | `admin` | all tenants | everything |

5. Playground: open https://play.10xgraph.com, set the API URL to `https://localhost` (or your
   `SITE_ADDRESS`), paste a token and chat. The browser must trust the Caddy certificate for the
   hosted playground to reach a local server, so do step 3 first.

## Approving a refund

Refunds above $100 stay pending on demo_server; the agent tells the customer they wait for staff.
A user with role `support`, `org_admin` or `admin` approves one with the same kind of token.
demo_server is not behind Caddy; with the dev override it listens on `127.0.0.1:8100`:

```bash
STAFF_TOKEN=$(.venv/bin/python deploy/scripts/make_token.py sam --name "Sam Lee" --role support --org acme)
curl -H "Authorization: Bearer $STAFF_TOKEN" "http://127.0.0.1:8100/v1/refunds?status=pending"
curl -X POST -H "Authorization: Bearer $STAFF_TOKEN" http://127.0.0.1:8100/v1/refunds/<refund_id>/approve
```

The route, the tenant check and the other endpoints are documented in `demo_server/README.md`.

## Deploy on a server

Set `SITE_ADDRESS` to your domain (DNS A record to the server, ports 80 and 443 open) and Caddy
gets a Let's Encrypt certificate on its own. Replace every password in `.env`. Do not use
`docker-compose.dev.yml`. Firewall everything except 22, 80 and 443.

## Internal dashboards (SSH tunnel)

These bind to `127.0.0.1` on the host only. On a server, reach them through a tunnel:

```bash
ssh -L 6006:127.0.0.1:6006 -L 3001:127.0.0.1:3001 -L 15672:127.0.0.1:15672 -L 9090:127.0.0.1:9090 user@server
```

| What | URL (through the tunnel) | Login |
|---|---|---|
| Phoenix (AI traces), project `support-desk` | http://127.0.0.1:6006 | `admin@localhost` / `admin` on first login, then a new password |
| Grafana, dashboard "10xGraph" | http://127.0.0.1:3001 | `admin` / `GRAFANA_ADMIN_PASSWORD` (anonymous access is off) |
| RabbitMQ management, queue `tenxgraph.events.demo` | http://127.0.0.1:15672 | `tenxgraph` / `RABBITMQ_PASSWORD` |
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
