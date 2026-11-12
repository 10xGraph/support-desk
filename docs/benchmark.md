# Benchmark: breaking point of the API container

One command finds where the 10xGraph API container (2 CPU, 4 GB, 2 gunicorn workers) stops coping
with load, and writes everything needed to analyse it elsewhere into one folder.

## What it measures

- The API server container only. It is limited to 2 CPU and 4 GB (`API_CPUS`, `API_MEMORY`).
  Postgres (max_connections 400), Redis, RabbitMQ, Phoenix, Prometheus, Grafana, the task worker,
  the scheduler, demo_server and the mock LLM run without limits and close to production: traces
  go to Phoenix, events to RabbitMQ, metrics to Prometheus, background jobs are on.
- The LLM is mocked by LLMock (300 to 800 ms per reply). Half the requests make the agent call
  `lookup_order` on demo_server, so one or two model calls per request.
- Closed-loop ramps on `/v1/graph/invoke` and `/v1/graph/stream`: N virtual users, each its own
  customer, send a request, wait for the answer, send the next. Each level runs `--step-seconds`
  (default 60). The ramp stops at the first level with more than 5 percent errors or a p99 above
  30 s. That level is the breaking point.
- Per level: req/s, p50/p90/p99, errors by kind, API peak CPU and memory, and the load
  generator's own CPU (to tell a client bottleneck from a server one).
- Optional: py-spy flame graph of the API (`--profile`) and the LLM-failure cases from
  `docs/load-testing.md` at a fixed level (`--chaos`).

It does not measure the real model, real tool latency, the knowledge-base search (Google
embeddings), network latency between machines, or Postgres/Redis/RabbitMQ limits (they are
unlimited on purpose). The load generator runs on the same machine, in the same Docker network.

## Prerequisites

- Linux with Docker Engine and Docker Compose 2.24 or newer (`docker compose version`; the override
  uses the `!reset` tag). 64 GB RAM and 8 or more cores recommended: the limited API container
  takes 2, the rest of the stack and the load generator need the others.
- No Python, curl or jq needed on the host: the load generator, the summary and the log counting
  run in containers.
- Internet access for the first build (images, PyPI, npm).

## Steps

1. Copy this whole folder to the machine (leave out `.venv/`).
2. Create `.env` from `.env.example` and set at least `POSTGRES_PASSWORD`, `RABBITMQ_PASSWORD`,
   `JWT_SECRET_KEY` (32 or more characters), `PHOENIX_SECRET`, `PHOENIX_ADMIN_SECRET`,
   `PHOENIX_ADMIN_PASSWORD`, `GRAFANA_ADMIN_PASSWORD` and `ORIGINS`. `deploy/scripts/make_secret.py`
   makes the secrets. `GOOGLE_API_KEY` is not used (the model is mocked). Do not change
   `ALLOWED_HOST` or `MODE`: the benchmark override sets the host list itself and the API runs in
   production mode.
3. Run:

   ```bash
   deploy/scripts/benchmark.sh --profile --chaos
   ```

   Options (defaults): `--workers "2 1"` (gunicorn workers to test, one ramp set each),
   `--levels 25,50,100,200,400,800,1200,1600,2400`, `--step-seconds 60`, `--modes "invoke stream"`,
   `--profile` (py-spy at `--profile-level 200` for 70 s per worker count), `--chaos` (level 100,
   `--chaos-seconds 60` per case). Other knobs go in `.env`: `API_CPUS`, `API_MEMORY`,
   `PG_POOL_MAX`.
4. Wait for "done" and the path of the tar.gz. The stack stays up; stop it with the `down` command
   the script prints (add `-v` to delete the data).

## How long

Build and start: 5 to 10 minutes the first time. Each ramp runs at most 9 levels of 60 s and
stops early at the breaking point, so 2 modes x 2 worker counts take 20 to 40 minutes. `--profile`
adds 70 s per worker count, `--chaos` about 5 minutes. Plan on one hour with `--profile --chaos`.

## What to send back

`benchmark_results/<timestamp>.tar.gz`. It holds `summary.md` (tables, breaking points), `meta.json`
(host, versions, settings), `ramp_*.json`, `stats_*.csv` (docker stats of every service every
5 s), the API logs (gzip) with a count of warnings and errors, `flame_*.svg` and `chaos_*.json`.
It contains no secrets: tokens are made in memory and `.env` is never copied.
