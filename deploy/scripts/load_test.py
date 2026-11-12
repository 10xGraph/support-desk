"""Load test the support agent through the API (use the mock LLM, see README).

Usage:
    .venv/bin/python deploy/scripts/load_test.py --users 50 --requests-per-user 4 --concurrency 20
    .venv/bin/python deploy/scripts/load_test.py --stream
    .venv/bin/python deploy/scripts/load_test.py --ramp 25,50,100,200 --step-seconds 60 \\
        --stats-container phoenix-demo-api-1 --out ramp.json
    .venv/bin/python deploy/scripts/load_test.py --chaos http:429 --chaos-frequency 5

Every user is a distinct user id (so the per-user rate limit is not the bottleneck) in acme or
globex. Every request starts a new thread. Half the messages ask about an order, which makes the
mock LLM call the lookup_order tool. Tokens are made in-process like make_token.py; the secret
from .env is never printed. Exits 1 if more than 1% of the requests fail.

Ramp mode (--ramp) runs a closed loop of N virtual users for --step-seconds at each level and stops
at the first level with more than 5% errors or a p99 above --max-p99. Each virtual user is a fresh
user id per step, renewed after 90 requests in a minute (the API allows 100 per user per minute).
"""

import argparse
import asyncio
import json
import os
import statistics
import time
import uuid
from collections import Counter

import aiohttp
import jwt
from dotenv import load_dotenv


# One order per company, the ones deploy/llmock/.llmockrc.json has rules for.
ORGS = {"acme": "A-1001", "globex": "G-2001"}
OTHER_MESSAGE = "Hello, I have a general question about your service."
MAX_USER_RATE = 90  # requests per user per 60 s, under the API limit of 100
MAX_ERROR_RATE = 0.05
UNITS = {"B": 1 / 2**20, "KiB": 1 / 1024, "MiB": 1, "GiB": 1024, "kB": 1 / 1000, "MB": 1, "GB": 1000}

parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
parser.add_argument("--users", type=int, default=20, help="distinct user ids")
parser.add_argument("--requests-per-user", type=int, default=5)
parser.add_argument("--concurrency", type=int, default=10, help="requests in flight")
parser.add_argument("--base-url", default="http://127.0.0.1:8000")
parser.add_argument("--stream", action="store_true", help="use /v1/graph/stream")
parser.add_argument("--timeout", type=float, default=60, help="seconds per request")
parser.add_argument("--ramp", help="comma list of concurrency levels, e.g. 25,50,100,200")
parser.add_argument("--step-seconds", type=float, default=60, help="ramp: seconds per level")
parser.add_argument("--max-p99", type=float, default=30, help="ramp: stop above this p99 (s)")
parser.add_argument(
    "--stats-container", action="append", default=[], help="ramp: container to watch (repeatable)"
)
parser.add_argument("--out", help="ramp: write the JSON results to this file (its folder is created)")
parser.add_argument("--label", default="", help="ramp: free text stored in the JSON results")
parser.add_argument(
    "--chaos", metavar="KIND[:STATUS]", help="llmock fails some LLM calls: http, stream-error, stream-drop or stream-stall"
)
parser.add_argument("--chaos-frequency", type=int, default=10, help="chaos: fail 1 in N calls")
parser.add_argument("--chaos-mode", choices=["every", "random"], default="random")
parser.add_argument("--llmock-url", default="http://127.0.0.1:8001", help="chaos: llmock admin address")
args = parser.parse_args()

load_dotenv()  # reads .env; nothing from it is printed
secret = os.environ["JWT_SECRET_KEY"]
algorithm = os.getenv("JWT_ALGORITHM", "HS256")
path = "/v1/graph/stream" if args.stream else "/v1/graph/invoke"


def make_token(user_id: str, org_id: str) -> str:
    now = int(time.time())
    claims = {
        "user_id": user_id,
        "name": user_id.capitalize(),
        "roles": ["member"],
        "org_id": org_id,
        "jti": uuid.uuid4().hex,
        "iat": now,
        "exp": now + 3600,
    }
    return jwt.encode(claims, secret, algorithm=algorithm)


def body(text: str) -> dict:
    return {"messages": [{"role": "user", "content": [{"type": "text", "text": text}]}]}


def stream_problem(content: bytes) -> str | None:
    """Scan a streamed body (one JSON chunk per line, see StreamChunk in tenxgraph core).

    A failed run sends a chunk {"event": "error", "data": {...}}; a run that finished sends a last
    chunk {"event": "updates", "data": {"status": "done"}}. No error and no done means a cut stream.
    """
    done = False
    for line in content.splitlines():
        try:
            chunk = json.loads(line)
        except ValueError:
            continue
        if not isinstance(chunk, dict):
            continue
        if chunk.get("event") == "error":
            return "stream_error"
        done = done or (chunk.get("data") or {}).get("status") == "done"
    return None if done else "stream_incomplete"


async def one_request(session, token: str, text: str) -> tuple:
    """Return (label, seconds, content). The label is "ok", an HTTP status, a stream problem or
    the exception type of a client-side failure (timeout, connection reset)."""
    start = time.perf_counter()
    try:
        async with session.post(
            args.base_url + path,
            json=body(text),
            headers={"Authorization": f"Bearer {token}"},
        ) as resp:
            content = await resp.read()  # the whole stream, if streaming
            label = "ok" if resp.status == 200 else str(resp.status)
    except Exception as exc:  # noqa: BLE001  a failed connection is a result too
        label, content = type(exc).__name__, str(exc).encode()
    if label == "ok" and args.stream:
        label = stream_problem(content) or "ok"
    return label, time.perf_counter() - start, content


def make_session() -> aiohttp.ClientSession:
    timeout = aiohttp.ClientTimeout(total=args.timeout)
    return aiohttp.ClientSession(timeout=timeout, connector=aiohttp.TCPConnector(limit=0))


def percentile(latencies: list[float], p: float) -> float:
    return latencies[min(len(latencies) - 1, int(p * len(latencies)))] if latencies else 0.0


async def run_once() -> int:
    sem = asyncio.Semaphore(args.concurrency)
    results: list[tuple] = []

    async def limited(session, token, text):
        async with sem:
            results.append(await one_request(session, token, text))

    tasks = []
    async with make_session() as session:
        for i in range(args.users):
            org, order = list(ORGS.items())[i % len(ORGS)]
            token = make_token(f"loaduser{i}", org)
            for n in range(args.requests_per_user):
                text = f"Where is my order {order}?" if n % 2 == 0 else OTHER_MESSAGE
                tasks.append(limited(session, token, text))
        start = time.perf_counter()
        await asyncio.gather(*tasks)
        elapsed = time.perf_counter() - start

    total = len(results)
    errors = [r for r in results if r[0] != "ok"]
    latencies = sorted(r[1] for r in results if r[0] == "ok")

    print(f"endpoint {path}  users {args.users}  concurrency {args.concurrency}")
    print(f"total {total}  ok {total - len(errors)}  errors {len(errors)}")
    for status, count in Counter(r[0] for r in errors).most_common():
        print(f"  status {status}: {count}")
    print(f"{total / elapsed:.1f} req/s over {elapsed:.1f}s")
    if latencies:
        print(
            f"latency s: p50 {statistics.median(latencies):.2f}  p90 {percentile(latencies, 0.90):.2f}  "
            f"p99 {percentile(latencies, 0.99):.2f}  max {latencies[-1]:.2f}"
        )
    for status, _, content in errors[:3]:
        print(f"error {status}: {content[:300].decode(errors='replace')}")
    return 1 if errors and len(errors) / total > 0.01 else 0


# ---- chaos (llmock admin API) ----


async def llmock(method: str, route: str, payload: dict | None = None) -> dict:
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session:
        async with session.request(method, args.llmock_url + route, json=payload) as resp:
            resp.raise_for_status()
            return await resp.json()


def chaos_body() -> dict:
    kind, _, status = args.chaos.partition(":")
    body = {"enabled": True, "frequency": args.chaos_frequency, "mode": args.chaos_mode, "kind": kind}
    if status:
        body["status"] = int(status)
    return body


async def with_chaos(run) -> int:
    """Run `run()` with llmock chaos on, and turn it off again afterwards, whatever happens."""
    if not args.chaos:
        return await run()
    body = chaos_body()
    await llmock("POST", "/admin/reset", {})  # call count back to 0, so mode "every" is repeatable
    await llmock("PATCH", "/admin/chaos", body)
    print(f"chaos {json.dumps(body)}  llmock {args.llmock_url}")
    try:
        code = await run()
        stats = (await llmock("GET", "/admin/chaos")).get("stats", {})
        print(f"llmock chaos: {stats.get('injected')} failures injected in {stats.get('calls')} LLM calls")
        return code
    finally:
        await llmock("PATCH", "/admin/chaos", {"enabled": False})
        print("chaos off")


# ---- ramp mode ----


async def docker(*cmd: str) -> str:
    proc = await asyncio.create_subprocess_exec(
        "docker", *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL
    )
    out, _ = await proc.communicate()
    return out.decode()


def to_mib(text: str) -> float:
    """'123.4MiB' -> 123.4"""
    number = text.strip().rstrip("BKiMGk")
    unit = text.strip()[len(number) :]
    return float(number) * UNITS.get(unit, 1)


async def sample_stats(peaks: dict, stop: asyncio.Event) -> None:
    """Every ~5 s record the peak CPU% and memory (MiB) of each watched container."""
    fmt = "{{.Name}}|{{.CPUPerc}}|{{.MemUsage}}"
    while not stop.is_set():
        for line in (await docker("stats", "--no-stream", "--format", fmt, *args.stats_container)).splitlines():
            try:
                name, cpu, mem = line.split("|")
                peak = peaks.setdefault(name, {"cpu": 0.0, "mem": 0.0})
                peak["cpu"] = max(peak["cpu"], float(cpu.rstrip("%")))
                peak["mem"] = max(peak["mem"], to_mib(mem.split("/")[0]))
            except ValueError:
                continue
        try:
            await asyncio.wait_for(stop.wait(), 5)
        except TimeoutError:
            pass


async def container_state(name: str) -> tuple[bool, int]:
    out = (await docker("inspect", "-f", "{{.State.OOMKilled}} {{.RestartCount}}", name)).split()
    return (out[0] == "true", int(out[1])) if len(out) == 2 else (False, 0)


async def virtual_user(session, vu: int, tag: str, end: float, results: list) -> None:
    """One closed-loop user: request, wait for the answer, request again until `end`.
    A new user id after MAX_USER_RATE requests inside one minute keeps the rate limit out of it."""
    org, order = list(ORGS.items())[vu % len(ORGS)]
    ident, sent, window_start, token = 0, 0, time.monotonic(), None
    n = 0
    while time.monotonic() < end:
        if token is None or time.monotonic() - window_start > 60:
            sent, window_start = 0, time.monotonic()
        if token is None or sent >= MAX_USER_RATE:
            ident += 1
            token = make_token(f"ramp{tag}u{vu}i{ident}", org)
            sent, window_start = 0, time.monotonic()
        text = f"Where is my order {order}?" if n % 2 == 0 else OTHER_MESSAGE
        results.append(await one_request(session, token, text))
        sent += 1
        n += 1


async def run_step(level: int, step: int) -> dict:
    results: list[tuple] = []
    peaks: dict = {}
    stop = asyncio.Event()
    start_ts = time.time()
    watcher = asyncio.create_task(sample_stats(peaks, stop)) if args.stats_container else None
    async with make_session() as session:
        start = time.monotonic()
        end = start + args.step_seconds
        tag = f"{uuid.uuid4().hex[:6]}s{step}"
        await asyncio.gather(*(virtual_user(session, v, tag, end, results) for v in range(level)))
        elapsed = time.monotonic() - start
    stop.set()
    if watcher:
        await watcher
    total = len(results)
    latencies = sorted(r[1] for r in results if r[0] == "ok")
    errors = Counter(r[0] for r in results if r[0] != "ok")
    return {
        "level": level,
        "start_ts": start_ts,
        "end_ts": time.time(),
        "total": total,
        "ok": total - sum(errors.values()),
        "errors": dict(errors),
        "error_rate": sum(errors.values()) / total if total else 1.0,
        "req_per_s": total / elapsed,
        "p50": statistics.median(latencies) if latencies else 0.0,
        "p90": percentile(latencies, 0.90),
        "p99": percentile(latencies, 0.99),
        "max": latencies[-1] if latencies else 0.0,
        "peaks": peaks,
    }


async def ramp() -> int:
    levels = [int(x) for x in args.ramp.split(",")]
    states = {c: await container_state(c) for c in args.stats_container}
    print(f"endpoint {path}  step {args.step_seconds:.0f}s  timeout {args.timeout:.0f}s  levels {levels}")
    steps, last_good, bad = [], None, None
    for i, level in enumerate(levels):
        step = await run_step(level, i)
        errs = " ".join(f"{k}:{v}" for k, v in sorted(step["errors"].items())) or "none"
        print(
            f"level {level:4d}  total {step['total']:5d}  ok {step['ok']:5d}  errors {errs}  "
            f"{step['req_per_s']:.1f} req/s  latency s p50 {step['p50']:.2f} p90 {step['p90']:.2f} "
            f"p99 {step['p99']:.2f} max {step['max']:.2f}"
        )
        step["containers"] = {}
        for name in args.stats_container:
            peak = next((v for k, v in step["peaks"].items() if k == name), {"cpu": 0.0, "mem": 0.0})
            oom, restarts = await container_state(name)
            restarted = restarts > states[name][1]
            step["containers"][name] = {**peak, "oom_killed": oom, "restarted": restarted}
            print(
                f"    {name}: peak cpu {peak['cpu']:.0f}%  peak mem {peak['mem']:.0f} MiB  "
                f"oom killed {oom}  restarted {restarted}"
            )
            states[name] = (states[name][0], restarts)
        steps.append(step)
        reason = None
        if step["error_rate"] > MAX_ERROR_RATE:
            reason = f"error rate {step['error_rate']:.1%} above {MAX_ERROR_RATE:.0%}"
        elif step["p99"] > args.max_p99:
            reason = f"p99 {step['p99']:.1f}s above {args.max_p99:.0f}s"
        if reason:
            bad = {"level": level, "reason": reason}
            break
        last_good = level
    if bad:
        print(f"breaking point: last good level {last_good}, first bad level {bad['level']} ({bad['reason']})")
    else:
        print(f"no breaking point: all levels up to {levels[-1]} were good")
    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        result = {
            "label": args.label,
            "endpoint": path,
            "chaos": args.chaos,
            "steps": steps,
            "last_good": last_good,
            "first_bad": bad,
        }
        with open(args.out, "w") as f:
            json.dump(result, f, indent=2)
    return 0


raise SystemExit(asyncio.run(with_chaos(ramp if args.ramp else run_once)))
