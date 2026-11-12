"""Helpers for deploy/scripts/benchmark.sh (standard library only).

    benchmark_summary.py summary RUN_DIR     write RUN_DIR/summary.md
    benchmark_summary.py logs LOG_FILE       print WARNING/ERROR messages, counted
"""

import csv
import glob
import json
import os
import re
import sys
from collections import Counter

UNITS = {"B": 1 / 2**20, "KiB": 1 / 1024, "MiB": 1, "GiB": 1024, "kB": 1 / 1000, "MB": 1, "GB": 1000}


def to_mib(text: str) -> float:
    match = re.match(r"([\d.]+)\s*([A-Za-z]+)", text.strip())
    return float(match.group(1)) * UNITS.get(match.group(2), 1) if match else 0.0


def load_stats(path: str) -> list[tuple]:
    """Rows of (epoch seconds, container name, cpu percent, memory MiB)."""
    rows = []
    if not os.path.exists(path):
        return rows
    with open(path) as f:
        for row in csv.reader(f):
            try:
                rows.append((float(row[0]), row[1], float(row[2].rstrip("%")), to_mib(row[3])))
            except (ValueError, IndexError):
                continue
    return rows


def peak(rows: list[tuple], name_pattern: str, start: float, end: float) -> tuple[float, float]:
    """Peak CPU % and memory MiB of the containers whose name matches, inside [start, end]."""
    found = [r for r in rows if start <= r[0] <= end + 5 and re.search(name_pattern, r[1])]
    return max((r[2] for r in found), default=0.0), max((r[3] for r in found), default=0.0)


def errors_text(errors: dict) -> str:
    return ", ".join(f"{k}:{v}" for k, v in sorted(errors.items())) or "0"


def ramp_section(path: str, run_dir: str) -> list[str]:
    name = os.path.basename(path)[len("ramp_") : -len(".json")]  # e.g. invoke_w2
    mode, _, workers = name.rpartition("_w")
    data = json.load(open(path))
    stats = load_stats(os.path.join(run_dir, f"stats_{name}.csv"))
    lines = [
        f"### {mode}, {workers} gunicorn workers",
        "",
        "| level | req/s | p50 s | p90 s | p99 s | errors | api peak CPU % | api peak mem MiB | loadgen peak CPU % |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for step in data["steps"]:
        api_cpu, api_mem = peak(stats, r"-api-\d+$", step["start_ts"], step["end_ts"])
        gen_cpu, _ = peak(stats, r"loadgen", step["start_ts"], step["end_ts"])
        lines.append(
            f"| {step['level']} | {step['req_per_s']:.1f} | {step['p50']:.2f} | {step['p90']:.2f} | "
            f"{step['p99']:.2f} | {errors_text(step['errors'])} | {api_cpu:.0f} | {api_mem:.0f} | {gen_cpu:.0f} |"
        )
    bad = data.get("first_bad")
    if bad:
        lines += ["", f"Breaking point: last good level {data['last_good']}, first bad level {bad['level']} ({bad['reason']})."]
    else:
        lines += ["", "No breaking point: every level was good."]
    state = os.path.join(run_dir, f"api_state_{name}.txt")
    if os.path.exists(state):
        lines += ["", "API container after the ramp: " + open(state).read().strip()]
    lines += ["", f"Files: `ramp_{name}.json`, `ramp_{name}.log`, `stats_{name}.csv`, `api_log_summary_{name}.txt`, `api_log_{name}.log.gz`", ""]
    return lines


def chaos_section(run_dir: str) -> list[str]:
    paths = sorted(glob.glob(os.path.join(run_dir, "chaos_*.json")))
    if not paths:
        return []
    lines = [
        "## Chaos",
        "",
        "| case | req/s | p50 s | p99 s | total | errors |",
        "|---|---|---|---|---|---|",
    ]
    for path in paths:
        step = json.load(open(path))["steps"][0]
        case = os.path.basename(path)[len("chaos_") : -len(".json")]
        lines.append(
            f"| {case} | {step['req_per_s']:.1f} | {step['p50']:.2f} | {step['p99']:.2f} | "
            f"{step['total']} | {errors_text(step['errors'])} |"
        )
    return lines + [""]


def summary(run_dir: str) -> None:
    meta = json.load(open(os.path.join(run_dir, "meta.json")))
    lines = [f"# Benchmark {meta.get('run')}", "", "## Setup", ""]
    for key, value in meta.items():
        lines.append(f"- {key}: {value}")
    lines += ["", "CPU % is as `docker stats` reports it: 100 is one core, so 200 is the limit of a 2 CPU container.", ""]
    lines += ["## Ramps", ""]
    for path in sorted(glob.glob(os.path.join(run_dir, "ramp_*.json"))):
        lines += ramp_section(path, run_dir)
    lines += chaos_section(run_dir)
    flames = sorted(glob.glob(os.path.join(run_dir, "flame_*.svg")))
    if flames:
        lines += ["## Flame graphs", ""] + [f"- `{os.path.basename(p)}`" for p in flames] + [""]
    lines += [
        "## Files",
        "",
        "`meta.json` (host and versions), `stats_*.csv` (docker stats every 5 s: epoch, container, CPU %, memory used, limit),",
        "`ramp_*.json` (full results per level), `api_log_*.log.gz` (API log of each ramp).",
    ]
    with open(os.path.join(run_dir, "summary.md"), "w") as f:
        f.write("\n".join(lines) + "\n")
    print(os.path.join(run_dir, "summary.md"))


def log_summary(path: str) -> None:
    """Count WARNING and ERROR messages (first 120 characters) in an API log."""
    counts: Counter = Counter()
    with open(path, errors="replace") as f:
        for line in f:
            try:
                entry = json.loads(line)
                level, message = entry.get("level", ""), str(entry.get("message", ""))
            except ValueError:
                match = re.search(r"\b(WARNING|ERROR|CRITICAL)\b", line)
                level, message = (match.group(1), line.strip()) if match else ("", "")
            if level in ("WARNING", "ERROR", "CRITICAL"):
                counts[(level, message[:120])] += 1
    for (level, message), count in counts.most_common():
        print(f"{count:7d}  {level:8s}  {message}")
    if not counts:
        print("no WARNING or ERROR lines")


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] not in ("summary", "logs"):
        raise SystemExit(__doc__)
    (summary if sys.argv[1] == "summary" else log_summary)(sys.argv[2])
