#!/bin/bash
# Set up a RunPod H100: install vLLM, download both formalizers, serve them on one GPU, health check.
# Usage: bash scripts/setup_pod.sh [--dry-run]
# Run from the repo root on the pod. Settings come from config.yaml (pod, models).
# Packages go into a venv (VENV, default /workspace/venv): the pod image's system Python refuses pip
# installs (PEP 668). PYTHON overrides the interpreter (the dry run uses the laptop's venv).
set -euo pipefail
cd "$(dirname "$0")/.."

DRY=0
[ "${1:-}" = "--dry-run" ] && DRY=1
VENV=${VENV:-/workspace/venv}
if [ -z "${PYTHON:-}" ]; then
  [ -x "$VENV/bin/python" ] || python3 -m venv "$VENV"
  export PATH="$VENV/bin:$PATH"
fi
PY=${PYTHON:-$VENV/bin/python}
run() { echo "+ $*"; if [ "$DRY" = 0 ]; then eval "$@"; fi; }
cfg() { "$PY" -c "import sys, yaml
v = yaml.safe_load(open('config.yaml'))
for k in sys.argv[1].split('/'): v = v[k]
print(v)" "$1"; }

[ "$DRY" = 0 ] && "$PY" -m pip install -q pyyaml
WORK=$(cfg pod/workdir)
VLLM=$(cfg pod/vllm_version)
MEM=$(cfg pod/gpu_memory_utilization)
MAXLEN=$(cfg pod/max_model_len)
QWEN=$(cfg models/qwen3-8b/hf_id)
REFORM=$(cfg models/reform-8b/hf_id)
LOGS="$WORK/logs"
port() { cfg "models/$1/base_url" | sed -E 's#.*:([0-9]+)/.*#\1#'; }
QPORT=$(port qwen3-8b)
RPORT=$(port reform-8b)

run "mkdir -p $LOGS"
# --no-cache-dir: the pod may have only its 50 GB container disk (no separate volume).
# vLLM pins its own numpy, which conflicts with ours; on the pod vLLM's wins (the analysis runs on the laptop).
run "grep -v '^numpy==' requirements.txt > /tmp/requirements_pod.txt"
run "$PY -m pip install -q --no-cache-dir vllm==$VLLM -r /tmp/requirements_pod.txt"
# Newer huggingface_hub ships `hf` in place of `huggingface-cli`.
HF=huggingface-cli
[ "$DRY" = 0 ] && command -v hf > /dev/null && HF=hf
run "$HF download $QWEN > $LOGS/download_qwen.log 2>&1"
run "$HF download $REFORM > $LOGS/download_reform.log 2>&1"
# Two servers share one H100: each gets a fixed share of GPU memory. They start one after the other:
# vLLM sizes its KV cache from the GPU memory free at startup, so two servers profiling at once each
# count the other's weights against their own share and fail with negative KV cache memory.
# The health check reads the served model name, not just a reply: RunPod's proxy may answer on a port.
wait_for() {
  local port=$1 name=$2
  if [ "$DRY" = 1 ]; then echo "+ wait until http://localhost:$port/v1/models serves $name (up to 20 min)"; return; fi
  for i in $(seq 1 120); do
    if curl -sf "http://localhost:$port/v1/models" | grep -q "\"id\":\"$name\""; then echo "$name on $port is up"; return; fi
    sleep 10
  done
  echo "server $name on $port did not come up; see $LOGS" >&2
  exit 1
}
run "nohup vllm serve $QWEN --served-model-name qwen3-8b --port $QPORT --gpu-memory-utilization $MEM --max-model-len $MAXLEN > $LOGS/vllm_qwen.log 2>&1 < /dev/null &"
wait_for "$QPORT" qwen3-8b
run "nohup vllm serve $REFORM --served-model-name reform-8b --port $RPORT --gpu-memory-utilization $MEM --max-model-len $MAXLEN > $LOGS/vllm_reform.log 2>&1 < /dev/null &"
wait_for "$RPORT" reform-8b
echo "both servers healthy"
