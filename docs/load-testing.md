# Load and chaos testing

Results from 2026-11-12. The support agent runs unchanged (ReactAgent, MCP tools on demo_server,
Postgres checkpointer, Redis, RabbitMQ events, Phoenix traces, Prometheus metrics). Only the LLM
is replaced by LLMock (`deploy/llmock/`, Anthropic format, replies after 300 to 800 ms). Half the
requests ask about an order, so the model calls `lookup_order` and answers again: one or two LLM
calls per request.

How to run it: README, "Load testing with a mock LLM".

## Setup

| Service | Limit | Settings |
|---|---|---|
| API | 2 CPU, 1 GB (`API_CPUS`, `API_MEMORY`) | 2 gunicorn workers, Postgres pool 20 per worker |
| Postgres | 2 CPU, 2 GB | max_connections 200, shared_buffers 512MB |
| demo_server, llmock, Redis, RabbitMQ, Phoenix | no limit | |

Every virtual user is its own customer (acme or globex) and starts a new thread per request.
Each level ran for 40 s, client timeout 60 s.

## Capacity, 2 CPU / 1 GB

`/v1/graph/invoke`:

| Concurrent users | Req/s | p50 | p99 | Errors |
|---|---|---|---|---|
| 50 | 30.3 | 1.5 s | 4.0 s | 0 |
| 100 | 42.6 | 2.3 s | 4.1 s | 0 |
| 200 | 43.1 | 4.4 s | 7.9 s | 0 |
| 400 | 40.7 | 8.7 s | 17.1 s | 0 |
| 800 | 36.3 | 19.4 s | 36.0 s | 0 |

The API CPU is the limit: it sits at 200% from 50 users on, and more users only queue. Memory
peaked at 560 MB of 1 GB; Postgres stayed under 100% CPU and 450 MB. No OOM, no restarts.

For comparison, 1 CPU / 1 GB tops out at about 21 req/s (p99 16 s at 200 users), times out 1.3%
of requests at 800 users and fails 75% at 1600 (client timeouts, and HTTP 500 when a request
waits too long for a Postgres connection). Throughput scales with CPU: about 20 req/s per core.
`/v1/graph/stream` reaches about 90% of the invoke rate.

## Chaos: the LLM fails 1 call in 10

100 concurrent users, 40 s per case. `--chaos` in `deploy/scripts/load_test.py`.

| Endpoint | LLM failure | Injected | Failed requests | Behaviour |
|---|---|---|---|---|
| invoke | HTTP 500 | 279 | 1 | Retried with backoff (up to 4 attempts) |
| invoke | HTTP 529 overloaded | 268 | 0 | Retried, honours `retry-after` |
| invoke | HTTP 429 rate limit | 304 | 0 | Retried, honours `retry-after` |
| invoke | HTTP 400 | 230 | 230 | Not retried (a bad request does not get better); HTTP 500 |
| stream | HTTP 500 | 232 | 0 | Retried before any output reaches the user |
| stream | HTTP 529 | 208 | 0 | Retried |
| stream | error mid-stream | 185 | 185 | Not retried: the user already saw part of the reply. Error event, thread saved with error status |
| stream | connection dropped mid-stream | 176 | 176 | Same as above |
| stream | model stalls mid-stream | 74 | 74 | Fails after the 30 s idle timeout (`TENXGRAPH_LLM_STREAM_IDLE_TIMEOUT`) |

Failed runs are saved with an error status, keep the user's message, and return a generic error
to the client (details only in the server log).

## Bugs found and fixed in core

- Streamed Anthropic calls were not retried at all when no stream idle timeout was set: 206 of
  206 injected 500s and 193 of 193 injected 529s failed the run. Fixed (stream open now runs
  inside the retry loop); the stream rows above are from the fixed core. Setting
  `TENXGRAPH_LLM_STREAM_IDLE_TIMEOUT`, as the compose file does, also avoided it.
- A Postgres pool timeout was logged with an empty message ("Failed to store checkpoint: ").
  It now names the error.
- Every new thread logged a WARNING ("No existing state found to reload"), about 4800 lines in one
  run. It is now DEBUG.

## Notes

- Without `TENXGRAPH_LLM_STREAM_IDLE_TIMEOUT`, a stalled model holds the run until `runs.timeout`
  (300 s in production). Set it.
- Keep the Postgres connection budget under `max_connections`: API workers x 2 pools x
  `PG_POOL_MAX`, plus the task worker, seed and demo_server.
