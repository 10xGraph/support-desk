#!/usr/bin/env bash
# Find the breaking point of the API container (2 CPU / 4 GB by default). See docs/benchmark.md.
#
#   deploy/scripts/benchmark.sh [--workers "2 1"] [--levels 25,50,100,...] [--step-seconds 60]
#                               [--modes "invoke stream"] [--profile] [--profile-level 200]
#                               [--chaos] [--chaos-seconds 60]
#
# Output: benchmark_results/<UTC timestamp>/ and benchmark_results/<UTC timestamp>.tar.gz.
# BENCH_COMPOSE_EXTRA="file1.yml file2.yml" adds more -f files (for example to move a port).
set -euo pipefail

WORKERS="2 1"
LEVELS="25,50,100,200,400,800,1200,1600,2400"
STEP_SECONDS=60
MODES="invoke stream"
PROFILE=0
PROFILE_LEVEL=200
CHAOS=0
CHAOS_SECONDS=60
CHAOS_LEVEL=100
MAX_P99=30

while [ $# -gt 0 ]; do
  case "$1" in
    --workers) WORKERS="$2"; shift 2 ;;
    --levels) LEVELS="$2"; shift 2 ;;
    --step-seconds) STEP_SECONDS="$2"; shift 2 ;;
    --modes) MODES="$2"; shift 2 ;;
    --profile) PROFILE=1; shift ;;
    --profile-level) PROFILE_LEVEL="$2"; shift 2 ;;
    --chaos) CHAOS=1; shift ;;
    --chaos-seconds) CHAOS_SECONDS="$2"; shift 2 ;;
    -h|--help) sed -n '2,9p' "$0"; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done

cd "$(dirname "$0")/../.."
[ -f .env ] || { echo "no .env here: copy .env.example to .env and fill it in" >&2; exit 1; }

FILES="-f docker-compose.yml -f docker-compose.benchmark.yml"
for extra in ${BENCH_COMPOSE_EXTRA:-}; do FILES="$FILES -f $extra"; done
COMPOSE="docker compose $FILES"
# Everything the benchmark needs. pgAdmin is left out on purpose.
STACK="api llmock postgres redis rabbitmq phoenix prometheus grafana worker scheduler demo-server"
STATS_SERVICES="api postgres redis rabbitmq phoenix worker demo-server llmock"

export BENCH_UID="$(id -u)" BENCH_GID="$(id -g)"
RUN="$(date -u +%Y%m%dT%H%M%SZ)"
OUT="benchmark_results/$RUN"
mkdir -p "$OUT"
log() { echo "[$(date -u +%H:%M:%S)] $*"; }
json_str() { printf '%s' "$1" | sed 's/\\/\\\\/g; s/"/\\"/g'; }

# The load generator runs inside the compose network and keeps its own results in /results.
# Its container is named bench-loadgen so the stats sampler can find it.
loadgen() { $COMPOSE run --rm -T --no-deps --name bench-loadgen loadgen "$@"; }

llmock_chaos() { # $1 = JSON body
  loadgen python -c "
import urllib.request as u
r = u.Request('http://llmock:8001/admin/chaos', data=b'$1', method='PATCH', headers={'Content-Type': 'application/json'})
print(u.urlopen(r, timeout=10).read()[:120])"
}
chaos_off() { llmock_chaos '{"enabled":false}' >/dev/null 2>&1 || true; }
trap chaos_off EXIT

# docker stats of the stack (and the load generator) every ~5 s, until the file $1.stop exists.
sample_stats() { # $1 = csv file
  echo "epoch,container,cpu,mem_used,mem_limit" > "$1"
  while [ ! -e "$1.stop" ]; do
    local ids now
    ids="$($COMPOSE ps -q $STATS_SERVICES) $(docker ps -q --filter name=bench-loadgen)"
    now="$(date +%s)"
    docker stats --no-stream --format '{{.Name}},{{.CPUPerc}},{{.MemUsage}}' $ids 2>/dev/null \
      | sed "s# / #,#; s#^#$now,#" >> "$1" || true
    sleep 3
  done
  rm -f "$1.stop"
}

api_id() { $COMPOSE ps -q api; }
api_state() { docker inspect -f 'OOMKilled={{.State.OOMKilled}} RestartCount={{.RestartCount}}' "$(api_id)"; }

start_api() { # $1 = gunicorn workers
  log "api with $1 workers"
  API_WORKERS="$1" $COMPOSE up -d --force-recreate --no-deps --wait api
}

ramp() { # $1 = mode, $2 = workers
  local mode="$1" w="$2" name="${1}_w${2}" flag="" since
  [ "$mode" = stream ] && flag="--stream"
  log "ramp $name: levels $LEVELS, $STEP_SECONDS s each"
  since="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "before: $(api_state)" > "$OUT/api_state_$name.txt"
  sample_stats "$OUT/stats_$name.csv" &
  local sampler=$!
  loadgen python deploy/scripts/load_test.py --base-url http://api:8000 $flag --ramp "$LEVELS" \
    --step-seconds "$STEP_SECONDS" --max-p99 "$MAX_P99" --label "$name" \
    --out "/results/$RUN/ramp_$name.json" 2>&1 | tee "$OUT/ramp_$name.log" || true
  touch "$OUT/stats_$name.csv.stop"; wait "$sampler" || true
  echo "after: $(api_state)" >> "$OUT/api_state_$name.txt"
  $COMPOSE logs --no-color --no-log-prefix --since "$since" api > "$OUT/api_log_$name.log" 2>&1 || true
  loadgen python deploy/scripts/benchmark_summary.py logs "/results/$RUN/api_log_$name.log" \
    > "$OUT/api_log_summary_$name.txt" 2>/dev/null || true
  gzip -f "$OUT/api_log_$name.log"
}

profile_run() { # $1 = workers: one fixed level while py-spy records 60 s
  log "profile at level $PROFILE_LEVEL, 70 s, workers $1"
  ( sleep 8; $COMPOSE run --rm -T --no-deps pyspy record --pid 1 --subprocesses --duration 60 --rate 50 \
      --format flamegraph -o "/results/$RUN/flame_w$1.svg" > "$OUT/pyspy_w$1.log" 2>&1 ) &
  local spy=$!
  loadgen python deploy/scripts/load_test.py --base-url http://api:8000 --ramp "$PROFILE_LEVEL" \
    --step-seconds 70 --max-p99 "$MAX_P99" --label "profile_w$1" \
    --out "/results/$RUN/profile_w$1.json" 2>&1 | tee "$OUT/profile_w$1.log" || true
  wait "$spy" || log "py-spy failed, see $OUT/pyspy_w$1.log"
}

chaos_run() { # $1 = mode, $2 = kind, $3 = workers
  local flag="" name="chaos_${1}_${2//:/}"
  [ "$1" = stream ] && flag="--stream"
  log "chaos $name at level $CHAOS_LEVEL for $CHAOS_SECONDS s"
  loadgen python deploy/scripts/load_test.py --base-url http://api:8000 $flag --ramp "$CHAOS_LEVEL" \
    --step-seconds "$CHAOS_SECONDS" --max-p99 "$MAX_P99" --chaos "$2" --llmock-url http://llmock:8001 \
    --label "$name" --out "/results/$RUN/$name.json" 2>&1 | tee "$OUT/$name.log" || true
}

# ---- start the stack ----
log "building and starting the stack"
$COMPOSE --profile bench build pyspy
$COMPOSE up -d --build --wait $STACK
chaos_off
first="${WORKERS%% *}"
start_api "$first"

# ---- metadata ----
cpu_model="$(grep -m1 'model name' /proc/cpuinfo | cut -d: -f2- | sed 's/^ *//' || true)"
versions="$(loadgen python -c "
import importlib.metadata as m
print(', '.join(p + ' ' + m.version(p) for p in ('10xgraph', '10xgraph-api', 'anthropic')))")"
inspect="$(docker inspect -f '{{.HostConfig.NanoCpus}} {{.HostConfig.Memory}}' "$(api_id)")"
pool="$(docker inspect -f '{{range .Config.Env}}{{println .}}{{end}}' "$(api_id)" | grep -E '^PG_POOL_MAX=|^TENXGRAPH_LLM_STREAM_IDLE_TIMEOUT=' | tr '\n' ' ')"
delay="$(grep -o '"responseDelay"[^}]*}' deploy/llmock/.llmockrc.json | head -1)"
cat > "$OUT/meta.json" <<META
{
  "run": "$RUN",
  "host_cpus": $(nproc),
  "host_ram": "$(json_str "$(free -h | awk '/^Mem:/ {print $2}')")",
  "cpu_model": "$(json_str "$cpu_model")",
  "kernel": "$(json_str "$(uname -r)")",
  "docker": "$(json_str "$(docker --version)")",
  "compose": "$(json_str "$(docker compose version --short)")",
  "versions": "$(json_str "$versions")",
  "api_cpus": "$(( ${inspect% *} / 1000000000 ))",
  "api_memory_bytes": "${inspect#* }",
  "api_env": "$(json_str "$pool")",
  "worker_counts": "$WORKERS",
  "levels": "$LEVELS",
  "step_seconds": "$STEP_SECONDS",
  "modes": "$MODES",
  "stop_rule": "error rate above 5 percent or p99 above $MAX_P99 s",
  "llmock_delay": "$(json_str "$delay")"
}
META

# ---- ramps ----
for w in $WORKERS; do
  [ "$w" = "$first" ] || start_api "$w"
  log "warmup"
  loadgen python deploy/scripts/load_test.py --base-url http://api:8000 --users 5 \
    --requests-per-user 4 --concurrency 5 > "$OUT/warmup_w$w.log" 2>&1 || true
  for mode in $MODES; do
    ramp "$mode" "$w"
    if [ "$PROFILE" = 1 ] && [ "$mode" = invoke ]; then profile_run "$w"; fi
  done
done

# ---- chaos (on the API as the last worker count left it) ----
if [ "$CHAOS" = 1 ]; then
  for mode in $MODES; do
    chaos_run "$mode" http:500
    chaos_run "$mode" http:529
  done
  case " $MODES " in *" stream "*) chaos_run stream stream-stall ;; esac
fi

chaos_off
loadgen python deploy/scripts/benchmark_summary.py summary "/results/$RUN"
tar -czf "benchmark_results/$RUN.tar.gz" -C benchmark_results "$RUN"
echo
log "done. Bring back: $(pwd)/benchmark_results/$RUN.tar.gz"
echo "The stack is still running. Stop it with: $COMPOSE down"
