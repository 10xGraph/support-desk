# Security review: support-desk API (port 8000)

Date: 2026-11-11. Target: the 10xGraph API server at http://127.0.0.1:8000, local stack only.

## Result

No critical, high, or medium vulnerabilities found. Authentication, tenant isolation,
authorization, rate limiting, request-size limits, CORS, security headers, and error handling all
behave correctly. One low-severity hardening gap is in the 10xGraph framework (server-software
header); it is reported upstream, not patched here.

## Scope

- In scope: the API on 8000 (auth, authorization, tenant isolation, input handling, rate limiting,
  headers, errors, load) and this project's code and config (`10xgraph.json`, `graph/`,
  `Dockerfile`, `docker-compose.yml`).
- Out of scope: demo_server (8100), Phoenix, Grafana, Prometheus, RabbitMQ, pgAdmin.
- Findings in the 10xGraph packages are reported, not patched in app code (project rule).

## Method

- Agent under test: `LOAD_TEST_AGENT=1` swaps the Gemini agent for `graph/load_test_agent.py`
  (2-second sleep, random canned reply, no LLM). Same API, JWT auth, Postgres/Redis checkpointer,
  tenant columns and callbacks, so every security path is real while tests and load cost nothing.
- Identities: `deploy/scripts/make_token.py`, two companies (`acme`, `globex`), all roles. The
  script reads the signing secret from `.env`; the review never read `.env`.
- Forged tokens were signed only with a deliberately wrong secret or `alg:none`.

## Static analysis

| Tool | Result |
|---|---|
| pip-audit (uv.lock export) | No known vulnerabilities |
| bandit (graph, demo_server, worker, deploy; tests excluded) | 0 issues |
| semgrep (python, fastapi, jwt, secrets, dockerfile, docker-compose) | Did not run: the semgrep engine is killed (out of memory) on this machine even on small inputs. Rerun elsewhere to close this gap. |
| gitleaks, trivy | Not installed (need a system package, `pacman -S gitleaks trivy`) |

## Dynamic tests

### Authentication / JWT (all rejected with 401, control accepted)
| Case | Status |
|---|---|
| No Authorization header | 401 |
| Empty bearer | 401 |
| Garbage token | 401 |
| Signed with wrong secret | 401 |
| `alg: none` (unsigned) | 401 |
| Expired | 401 |
| Valid token (control) | 200 |

### Tenant isolation and privilege (acme vs globex, all valid tokens)
| Case | Status | Note |
|---|---|---|
| Client-chosen thread_id for a fresh run | 404 `THREAD_NOT_FOUND` | Server assigns IDs; no thread-ID squatting or guessing across tenants |
| globex GET acme thread state (real ID) | 404 | Blocked |
| globex GET acme thread messages | 404 | Blocked |
| globex DELETE acme thread | 404 | Blocked |
| globex PUT acme state | 422/blocked | Not owner |
| globex DELETE acme state | 404 | Blocked |
| globex store search | 403 | Blocked |
| acme invoke with `config.user` org=globex, role=admin | 200, ignored | Thread owner stays `alice`; injected claims had no effect |
| acme invoke with `initial_state.org_id=globex` | 200, ignored | Server uses the verified token identity |
| acme on its own thread (control) | 200 | Works |

Identity is taken from the verified JWT only. Client-supplied `config.user`, `initial_state`,
and body `config.thread_id` cannot change the tenant, owner, or role. The DELETE route applies the
path `thread_id` after the body config, so the body cannot redirect the call.

### Input handling / DoS
| Case | Status |
|---|---|
| 10 MB request body | Connection refused at the 10 MB limit (`MAX_REQUEST_SIZE`) |
| 5 MB text field | 422 (per-field validation before processing) |
| 1000-level nested config | 422 (BoundedDict depth limit) |
| 100k-key initial_state | 422 (BoundedDict size limit) |
| Malformed JSON | 422, generic message, no stack trace |

### Rate limiting
- 120 rapid requests as one user: 100 pass, 20 get 429. Per-user limit (100 / 60 s) enforced.
- 429 carries `Retry-After: 60`, `X-RateLimit-Limit`, `X-RateLimit-Remaining`,
  `X-RateLimit-Reset`, `X-RateLimit-Reset-After`.

### Headers and CORS
- Present on responses: `Content-Security-Policy`, `X-Frame-Options: DENY`,
  `X-Content-Type-Options: nosniff`, `X-XSS-Protection`, `Cache-Control: no-store`, `Vary: Origin`.
- CORS preflight from `https://evil.example`: 400, no `Access-Control-Allow-Origin` echoed. Foreign
  origins are rejected.
- Error bodies are generic (`VALIDATION_ERROR`, empty `details`): no schema or stack-trace leak.

### Load (fake agent, 2 s latency)
- 60 concurrent invokes across 20 users, concurrency 20: 60/60 succeeded in 7.3 s.
- Latency p50 2.25 s, p95 2.58 s, max 2.60 s (fake latency + ~0.1-0.6 s overhead). Scales cleanly;
  no errors, no connection-pool exhaustion.

## Findings

### LOW-1: Server software disclosed in the `Server` header (framework)
- Every response carries `Server: uvicorn`, revealing the server software.
- Impact: minor information disclosure; eases fingerprinting. No direct exploit.
- Root cause: the framework's gunicorn/uvicorn worker
  (`tenxgraph_api.src.app.uvicorn_worker.TenxGraphUvicornWorker.CONFIG_KWARGS`) does not set
  `server_header=False`, and the security-headers middleware does not strip `Server`.
- Fix: upstream in 10xGraph (add `"server_header": False` to the worker's `CONFIG_KWARGS`, or
  delete the header in the security-headers middleware). Per the project rule, not worked around
  in app code. Report to 10xGraph.

## Notes / non-defects
- 422 validation errors return an empty `details` list. This hides schema details from attackers;
  it is intentional and not a defect.
- `/docs`, `/redocs`, `/openapi.json`, `/metrics` all return 404 in production mode. Good.

## Open items
- Run semgrep on a machine with more memory.
- Install and run gitleaks (secret history) and trivy (image scan).

## Restore after testing
- Remove `LOAD_TEST_AGENT` from `.env` (or set it to anything but `1`) and
  `docker compose up -d --build api` to bring back the real Gemini agent.
- `graph/load_test_agent.py` and the `LOAD_TEST_AGENT` branch in `graph/agent.py` are inert while
  the variable is unset.
