"""Measure Gemini implicit prompt caching for different prompt layouts.

Run from the project root (reads GOOGLE_API_KEY, or Vertex settings, from .env):
    .venv/bin/python cache_experiment.py

Writes every call and a summary to cache_experiment_results.txt (also printed). Uses the
google-genai SDK directly, not 10xGraph, so only the prompt layout varies.

Scenarios (each repeated REPEATS times with a fresh session id at the start of the system
instruction, so runs never share a cache):
  S0 identical  the same request twice: does implicit caching hit at all?
  S1 ctx_end    system, history, user message, context            (context last)
  S2 ctx_before system, history, context, user message            (context before the message)
  S3 ctx_system context inside the system instruction             (the old design)
  S4 cross_user one system prompt, three users with different messages
  S5 tool_loop  context after a function response, two calls in one tool loop

Env overrides: CACHE_TEST_MODEL (default gemini-2.5-flash), REPEATS (2), SLEEP seconds (3).
Cost: roughly 150k input tokens on gemini-2.5-flash.
"""

import os
import time
import traceback
import uuid
from datetime import UTC, datetime
from pathlib import Path

from dotenv import load_dotenv
from google import genai
from google.genai import types


load_dotenv()

MODEL = os.getenv("CACHE_TEST_MODEL", "gemini-2.5-flash")
REPEATS = int(os.getenv("REPEATS", "2"))
SLEEP = float(os.getenv("SLEEP", "3"))
TURNS = 5
OUT = Path(__file__).resolve().parent / "cache_experiment_results.txt"

# About 2,000 tokens of fixed instructions, above the 1,024-token minimum of 2.5 Flash.
RULES = "\n".join(
    f"Rule {i}: When a customer asks about topic {i}, answer politely, check the order with the "
    f"lookup tool first, never promise a refund above the limit, and keep the reply under "
    f"{50 + i} words. Mention the warranty only if the product category is {i % 7}."
    for i in range(1, 46)
)

USER_MESSAGES = [
    "Hi, my monitor from order A-1002 arrived with a cracked screen.",
    "Can I get a full refund for it? It cost 250 dollars.",
    "How long does the staff approval usually take?",
    "Also, does the warranty cover water damage on the headset?",
    "Thanks. Please open a ticket so a person can call me back.",
]
ASSISTANT_REPLY = (
    "Thank you for the details. I checked your order and I understand the problem. "
    "Here is what happens next: the request goes through our normal process, I keep you "
    "informed at every step, and you can ask me anything else in the meantime. " * 3
)

_lines: list[str] = []


def log(line: str = "") -> None:
    print(line)
    _lines.append(line)
    OUT.write_text("\n".join(_lines) + "\n", encoding="utf-8")


def text(role: str, value: str) -> types.Content:
    return types.Content(role=role, parts=[types.Part.from_text(text=value)])


def context_block(turn: int) -> str:
    return (
        "<conversation_context>\n"
        f"Today: 2026-11-11\nLast ticket in this conversation: ACME-{1040 + turn}\n"
        "</conversation_context>"
    )


def history(turns: int) -> list[types.Content]:
    contents: list[types.Content] = []
    for i in range(turns):
        contents.append(text("user", USER_MESSAGES[i]))
        contents.append(text("model", ASSISTANT_REPLY))
    return contents


def system(session: str, extra: str = "") -> str:
    return f"Session {session}.\nYou are a support agent.\n{RULES}\n{extra}".rstrip()


client: genai.Client | None = None  # created in main(), after .env is loaded
gen_config = {"temperature": 0, "max_output_tokens": 16}
if "2.5-flash" in MODEL:
    gen_config["thinking_config"] = types.ThinkingConfig(thinking_budget=0)

rows: list[dict] = []


def call(scenario: str, rep: int, step: str, system_instruction: str, contents) -> None:
    config = types.GenerateContentConfig(system_instruction=system_instruction, **gen_config)
    row = {"scenario": scenario, "rep": rep, "step": step}
    try:
        response = client.models.generate_content(model=MODEL, contents=contents, config=config)
        usage = response.usage_metadata
        row["prompt"] = usage.prompt_token_count or 0
        row["cached"] = usage.cached_content_token_count or 0
        row["error"] = ""
    except Exception as exc:  # record and continue: a refused layout is a result too
        row["prompt"] = row["cached"] = 0
        row["error"] = f"{type(exc).__name__}: {exc}"[:300]
    rows.append(row)
    pct = f"{100 * row['cached'] / row['prompt']:.0f}%" if row["prompt"] else "-"
    log(
        f"{scenario:<11} rep={rep} {step:<14} prompt={row['prompt']:>6} "
        f"cached={row['cached']:>6} hit={pct:>4} {row['error']}"
    )
    time.sleep(SLEEP)


def s0_identical(rep: int) -> None:
    sid = uuid.uuid4().hex[:8]
    contents = [*history(2), text("user", USER_MESSAGES[2])]
    for step in ("first", "second", "third"):
        call("S0_identical", rep, step, system(sid), contents)


def s1_ctx_end(rep: int) -> None:
    sid = uuid.uuid4().hex[:8]
    for t in range(TURNS):
        contents = [*history(t), text("user", USER_MESSAGES[t]), text("user", context_block(t))]
        call("S1_ctx_end", rep, f"turn{t + 1}", system(sid), contents)


def s2_ctx_before(rep: int) -> None:
    sid = uuid.uuid4().hex[:8]
    for t in range(TURNS):
        contents = [*history(t), text("user", context_block(t)), text("user", USER_MESSAGES[t])]
        call("S2_ctx_before", rep, f"turn{t + 1}", system(sid), contents)


def s3_ctx_system(rep: int) -> None:
    sid = uuid.uuid4().hex[:8]
    for t in range(TURNS):
        contents = [*history(t), text("user", USER_MESSAGES[t])]
        call("S3_ctx_system", rep, f"turn{t + 1}", system(sid, context_block(t)), contents)


def s4_cross_user(rep: int) -> None:
    sid = uuid.uuid4().hex[:8]  # one shared system prompt for all users
    for user, message in (
        ("userA", USER_MESSAGES[0]),
        ("userB", USER_MESSAGES[3]),
        ("userC", USER_MESSAGES[4]),
    ):
        call("S4_cross", rep, user, system(sid), [text("user", message)])


def s5_tool_loop(rep: int) -> None:
    sid = uuid.uuid4().hex[:8]
    calls = types.Content(
        role="model",
        parts=[types.Part.from_function_call(name="lookup_order", args={"order_id": "A-1002"})],
    )
    result = types.Content(
        role="user",
        parts=[
            types.Part.from_function_response(
                name="lookup_order",
                response={"result": "Order A-1002: 27-inch monitor, $250.00, delivered."},
            )
        ],
    )
    base = [*history(2), text("user", USER_MESSAGES[2])]
    call("S5_tool", rep, "call1", system(sid), [*base, text("user", context_block(0))])
    call(
        "S5_tool",
        rep,
        "call2_after_fr",
        system(sid),
        [*base, calls, result, text("user", context_block(0))],
    )


SCENARIOS = [s0_identical, s1_ctx_end, s2_ctx_before, s3_ctx_system, s4_cross_user, s5_tool_loop]


def summary() -> None:
    log("")
    log("SUMMARY (calls after the first of each run; the first call of a new prefix is a miss)")
    log(f"{'scenario':<14} {'calls':>5} {'prompt':>8} {'cached':>8} {'hit':>5} errors")
    by: dict[str, list[dict]] = {}
    for row in rows:
        by.setdefault(row["scenario"], []).append(row)
    for scenario, items in by.items():
        later = [r for r in items if r["step"] not in ("first", "turn1", "userA", "call1")]
        prompt = sum(r["prompt"] for r in later)
        cached = sum(r["cached"] for r in later)
        errors = sum(1 for r in items if r["error"])
        pct = f"{100 * cached / prompt:.0f}%" if prompt else "-"
        log(f"{scenario:<14} {len(later):>5} {prompt:>8} {cached:>8} {pct:>5} {errors}")


def main() -> None:
    global client  # noqa: PLW0603
    if not (
        os.getenv("GOOGLE_API_KEY")
        or os.getenv("GEMINI_API_KEY")
        or os.getenv("GOOGLE_GENAI_USE_VERTEXAI")
    ):
        raise SystemExit("Set GOOGLE_API_KEY (or Vertex settings) in .env or the environment.")
    # google-genai 3.x defaults to API version v1, which rejects system_instruction
    # ("Developer instruction is not enabled for api version v1"). 10xGraph pins v1beta too
    # (tenxgraph/core/llm/client_factory.py).
    vertex = os.getenv("GOOGLE_GENAI_USE_VERTEXAI", "").lower() in ("1", "true")
    client = (
        genai.Client()
        if vertex
        else genai.Client(http_options=types.HttpOptions(api_version="v1beta"))
    )
    log(f"Gemini implicit caching experiment, {datetime.now(UTC).isoformat(timespec='seconds')}")
    log(f"model={MODEL} google-genai={genai.__version__} repeats={REPEATS} sleep={SLEEP}s")
    try:
        rules = client.models.count_tokens(model=MODEL, contents=RULES).total_tokens
        log(f"static rules alone: {rules} tokens")
    except Exception as exc:
        log(f"count_tokens failed: {type(exc).__name__}: {exc}")
    log("")
    for rep in range(1, REPEATS + 1):
        for scenario in SCENARIOS:
            try:
                scenario(rep)
            except Exception:
                log(f"{scenario.__name__} rep={rep} crashed:\n{traceback.format_exc()}")
    summary()
    log(f"\nWritten to {OUT}")


if __name__ == "__main__":
    main()
