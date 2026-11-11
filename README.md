# support-desk

A multi-tenant customer support agent built on [10xGraph](https://10xgraph.com), with the full
production stack in Docker Compose: authentication and roles, tenant isolation, tools over MCP,
a knowledge base in pgvector, background jobs, AI traces, metrics and evaluations.

Two demo companies, `acme` and `globex`, share one deployment. Each customer sees only their own
company's orders, tickets and knowledge base, and the agent cannot be talked into crossing that
line: the company comes from the signed-in user's token, never from the conversation.

## What it shows

| 10xGraph feature | Where |
|---|---|
| One prebuilt `ReactAgent` (Gemini), no hand-written graph | `graph/agent.py` |
| Tools from an MCP server, with a signed short-lived token per call (`mcp_auth`) | `graph/support_tools.py`, `demo_server/` |
| Business rules in the company's own service, not in the agent | `demo_server/` |
| Knowledge base as search-only agent memory (PgVectorStore, Google embeddings), one per tenant | `graph/agent.py`, `deploy/scripts/seed_knowledge_base.py` |
| JWT auth, roles with reach `own` / `tenant` / `all`, tenant claim `org_id` | `10xgraph.json` |
| State filled from the verified token by a lifecycle hook | `graph/validators/lifecyle.py`, `graph/state.py` |
| Prompt layout for provider prompt caching | `graph/prompts.py`, `docs/prompt-caching.md` |
| Durable threads (Postgres) with a Redis hot cache | `graph/agent.py` |
| Rate limiting, token revocation, audit log | `10xgraph.json` |
| Background tasks and a scheduler (TaskIQ over RabbitMQ) | `worker/tasks.py` |
| Graph events to RabbitMQ, AI traces to Phoenix, metrics to Prometheus and Grafana | `graph/agent.py`, `10xgraph.json`, `deploy/` |
| Evaluations with a real model: scripted cases and a simulated user | `evals/` |

## How it works

```
                 Bearer JWT (user_id, roles, org_id)
  client ───────────────────────────────────────────▶  API (10xgraph-api, :8000)
                                                         │
                                                         ▼
                                               ReactAgent (Gemini)
                     ┌──────────────────────────────┼───────────────────────────┐
                     ▼                              ▼                           ▼
        knowledge base search           MCP tools, 60 s token per call     threads
        (pgvector, per tenant)          naming customer + agent            (Postgres + Redis)
                                                    │
                                                    ▼
                                         demo_server (:8100)
                                   orders, refunds, tickets (schema demo)
```

- **The agent** is one `ReactAgent`: a model node and a tool node in a loop. It has no routers,
  guard nodes or approval steps.
- **The tools** (`lookup_order`, `refund_order`, `create_ticket`) live in `demo_server`, a plain
  FastAPI app standing in for the company's own systems. It serves REST for staff and MCP for
  the agent.
- **Identity on every tool call.** For each call the agent signs a 60-second JWT with audience
  `demo-mcp`. The token names the signed-in customer and the agent as actor (`act.sub`).
  demo_server verifies it and takes the customer and company from it. Tools have no `user_id` or
  `org_id` arguments, and the customer's own API token is never forwarded.
- **The rules** live in demo_server, not in the prompt:
  - refunds up to $100 are issued at once;
  - larger ones stay pending until staff approve them;
  - each order gets at most one refund.
- **The knowledge base** holds product help and policies per company. The agent searches it with
  `agent_memory_tool`. A seed step loads it when the stack starts.

## Quick start

Requirements:
- Docker with Compose;
- [uv](https://docs.astral.sh/uv/) for the helper scripts and evals;
- a Google AI API key for Gemini and the embeddings.

1. Install the project locally (for the scripts and evals):

   ```bash
   uv sync --extra test
   ```

2. Create `.env` and the secrets:

   ```bash
   cp .env.example .env
   uv run python deploy/scripts/make_secret.py   # JWT_SECRET_KEY, PHOENIX_SECRET, PHOENIX_ADMIN_SECRET
   ```

   Then edit `.env`:
   - set `GOOGLE_API_KEY`;
   - replace every `change-me` password;
   - use the same Postgres and RabbitMQ passwords inside `DATABASE_URL` and `BROKER_URL`.

   Keep the passwords URL-safe.

3. Start the stack:

   ```bash
   docker compose up --build
   ```

   Postgres starts, `seed` loads the knowledge base and exits, then the API starts.
   `curl http://localhost:8000/ping` answers when it is ready.

## Try it

Make a token for a customer. The script reads `.env` and prints only the token:

```bash
TOKEN=$(uv run python deploy/scripts/make_token.py alice --name "Alice Chen" --org acme)
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/v1/me   # role, tenant, reach
```

Chat through the API:

```bash
curl -X POST http://localhost:8000/v1/graph/invoke \
  -H "Authorization: Bearer $TOKEN" -H 'content-type: application/json' \
  -d '{"messages":[{"role":"user","content":[{"type":"text","text":"Where is my order A-1003?"}]}]}'
```

Or open the [10xGraph playground](https://play.10xgraph.com), set the API URL to
`http://localhost:8000` and paste the token.

Things to ask:

| Ask as | Message | What happens |
|---|---|---|
| `alice` (acme) | Where is my order A-1003? | `lookup_order`: shipped |
| `alice` (acme) | My monitor from order A-1002 arrived cracked, refund it | $250 refund, pending staff approval |
| `alice` (acme) | How do I pair my wireless headset? | answer from acme's knowledge base |
| `alice` (acme) | I want to talk to a person | `create_ticket`, ticket `ACME-...` |
| `bob` (globex) | What is the status of order A-1002? | not found: A-1002 belongs to acme |
| `bob` (globex) | My standing desk shows error E01 | answer from globex's knowledge base |

### Roles

| Role | Reach | Can do |
|---|---|---|
| `member` (default) | own threads | chat, own threads and files |
| `support` | whole tenant | read the tenant's threads, approve refunds on demo_server |
| `org_admin` | whole tenant | support, plus delete, graph read and fix |
| `admin` | all tenants | everything |

```bash
uv run python deploy/scripts/make_token.py sam --name "Sam Lee" --role support --org acme
```

### Approving a refund

Refunds over $100 wait for staff. A `support`, `org_admin` or `admin` user of the same company
approves them on demo_server. A user cannot approve a refund they requested.

```bash
STAFF=$(uv run python deploy/scripts/make_token.py sam --name "Sam Lee" --role support --org acme)
curl -H "Authorization: Bearer $STAFF" "http://127.0.0.1:8100/v1/refunds?status=pending"
curl -X POST -H "Authorization: Bearer $STAFF" http://127.0.0.1:8100/v1/refunds/<refund_id>/approve
```

The endpoints are listed in [demo_server/README.md](demo_server/README.md).

### Background jobs

The `worker` and `scheduler` services run TaskIQ over RabbitMQ, with status and results in
Redis. The `worker` block in `10xgraph.json` lists the task modules. The tasks in
`worker/tasks.py` are examples:

```bash
curl -X POST http://localhost:8000/v1/tasks/summarize_thread \
  -H "Authorization: Bearer $TOKEN" -H 'content-type: application/json' \
  -d '{"kwargs": {"thread_id": "<thread id>"}}'
docker compose logs -f worker
```

Run exactly one scheduler.

## Observability

| What | URL | Login |
|---|---|---|
| Phoenix: AI traces, project `support-desk` | http://127.0.0.1:6006 | `admin@localhost` / `PHOENIX_ADMIN_PASSWORD` |
| Grafana: dashboard "10xGraph" | http://127.0.0.1:3001 | `admin` / `GRAFANA_ADMIN_PASSWORD` |
| RabbitMQ: queue `tenxgraph.events.demo` | http://127.0.0.1:15672 | `tenxgraph` / `RABBITMQ_PASSWORD` |
| Prometheus | http://127.0.0.1:9090 | none; query `{job="support-agent"}` |
| pgAdmin: server `support-desk` | http://127.0.0.1:5050 | `PGADMIN_EMAIL` / `PGADMIN_PASSWORD` |

How the data gets there:
- **Phoenix:** every run becomes one trace (graph, node, model and tool steps), with the input,
  output and graph state of each step. Turn it on with `observability` in `10xgraph.json`.
- **Prometheus and Grafana:** the API pushes metrics to Prometheus over OTLP (`metrics` in
  `10xgraph.json`). Grafana reads Prometheus through the files in `deploy/grafana/`.
- **RabbitMQ:** `graph/agent.py` passes a `RabbitMQPublisher`, so graph events go to the
  exchange `tenxgraph.events`. The queue `tenxgraph.events.demo` keeps a copy to inspect.
- **Logs:** audit events and JSON logs go to the API's stdout. Run
  `docker compose logs api | grep tenxgraph_api.audit` to see the audit events.

## Tests and evaluations

```bash
uv run pytest                        # agent wiring, no model calls
uv run pytest demo_server/tests      # demo_server rules
```

Some demo_server tests need a Postgres they may reset the `demo` schema of. Point
`TEST_DATABASE_URL` at the stack's database (`127.0.0.1:5433`) to run them.

Evaluations call the real model and the running stack (they need `GOOGLE_API_KEY`):

```bash
uv run 10xgraph eval evals/support_agent_eval.py     # scripted cases
uv run 10xgraph eval                                 # plus the simulated-user scenarios
```

Each case runs as a signed-in customer from `evals/customers.py`. Reports go to `eval_reports/`.

## Project layout

```
graph/                 the agent: agent.py, prompts.py, state.py, MCP auth, lifecycle hook
demo_server/           the company's systems: orders, refunds, tickets; REST + MCP
worker/tasks.py        background tasks
evals/                 evaluations with the real model
tests/                 fast unit tests, no model calls
deploy/                Grafana, Prometheus, RabbitMQ config; seed, secret and token scripts
docs/prompt-caching.md how the prompt is laid out for provider caching
10xgraph.json          API config: auth and roles, rate limits, observability, metrics, jobs
docker-compose.yml     the whole stack
```

## Before you deploy it

This compose file is set up to run on one machine:
- **Ports:** every port binds to `127.0.0.1`.
- **No TLS:** there is no reverse proxy or certificate yet.

To serve it:
- **Proxy:** put a TLS reverse proxy in front of the API only (`deploy/caddy/Caddyfile` is a
  starting point).
- **Passwords:** replace every password.
- **Internal services:** keep demo_server, Phoenix and the dashboards off the public network.
  Anyone holding `JWT_SECRET_KEY` can sign demo_server tokens.

Passwords in `.env` are applied when a volume is first created. After changing one, either reset
with `docker compose down -v` (this deletes all data) or change it inside the service too.

## Learn more

- 10xGraph docs: https://10xgraph.com
- Core framework: https://github.com/10xGraph/10xGraph
- API server and CLI: https://github.com/10xGraph/10xgraph-api
- TypeScript client: https://github.com/10xGraph/10xgraph-client

## License

[MIT](LICENSE)
