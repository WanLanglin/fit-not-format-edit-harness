#!/usr/bin/env bash
# Run pilot.py behind a dedicated recording proxy, then summarize.
#   [PROXY_CONFIG=configs/x.json] run_with_proxy.sh OUTPUT_DIR MAX_COST_USD [--save-streams] -- PILOT_ARGS...
# The OpenRouter key is loaded only into the proxy; pilot.py and S-Code run without it.
# PROXY_CONFIG defaults to configs/openrouter-pilot.json.
set -u
cd "$(dirname "$0")"
out=$1 budget=$2; shift 2
proxy_flags=()
while [ "$#" -gt 0 ] && [ "$1" != "--" ]; do proxy_flags+=("$1"); shift; done
[ "${1:-}" = "--" ] && shift
mkdir -p "$out"; rm -f "$out/proxy.port"
(set -a && { [ -f ~/.config/editbench/openrouter.env ] && . ~/.config/editbench/openrouter.env || true; } && set +a
 exec "${PYTHON:-python3}" orproxy.py --config "${PROXY_CONFIG:-configs/openrouter-pilot.json}" --runs-dir "$out" --max-cost-usd "$budget" \
   --port-file "$out/proxy.port" "${proxy_flags[@]}") > "$out/proxy.stdout" 2> "$out/proxy.stderr" &
proxy=$!
for _ in $(seq 100); do [ -s "$out/proxy.port" ] && break; sleep 0.1; done
if [ ! -s "$out/proxy.port" ]; then echo "proxy for $out did not start"; kill "$proxy" 2>/dev/null; exit 1; fi
port=$(cat "$out/proxy.port")
echo "proxy $out on $port (pid $proxy)"
env -u EDITBENCH_OPENROUTER_API_KEY -u OPENROUTER_API_KEY "${PYTHON:-python3}" pilot.py --output "$out" \
  --s-code "${S_CODE_BIN:-bin/79878f3/s-code}" --base-url "http://127.0.0.1:$port/r/{run_id}/v1" "$@" 2>&1 | grep -E '"status"'
kill "$proxy" 2>/dev/null
wait "$proxy" 2>/dev/null
"${PYTHON:-python3}" summarize_pilot.py "$out" | grep -vE '^\s*$'
