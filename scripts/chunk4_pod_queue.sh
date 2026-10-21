#!/bin/bash
# Chunk 4: everything the pod does today, unattended, in one tmux session.
#   1. wait for setup_pod.sh to finish healthy, then check the API preflight gate (closed: stop the pod)
#   2. the 150-call GEPA pilot run (pushes its results, keeps the pod running)
#   3. the chunk 5 combined job's dry run (pushes its results, then stops the pod)
# Usage on the pod, from the repo root: tmux new-session -d -s queue "bash scripts/chunk4_pod_queue.sh"
# If setup fails, nothing runs and the pod is left up for a look (setup.log says why).
set -uo pipefail
cd "$(dirname "$0")/.."
export PATH=/workspace/venv/bin:$PATH
unset TMUX   # run_job.sh opens its own tmux sessions from inside this one
LOG=/workspace/logs/queue.log
mkdir -p /workspace/logs
say() { echo "[$(date -u +%FT%TZ)] $*" >> "$LOG"; }

say "waiting for setup"
until grep -q "^EXIT" /workspace/setup.log 2>/dev/null; do sleep 10; done
if ! grep -q "^EXIT 0" /workspace/setup.log; then say "setup failed; stopping the queue"; exit 1; fi
# Gate (Neel): no GEPA unless the committed API preflight passed in full and is recent. Fails closed.
if ! python -m scripts.chunk4 preflight_ok >> "$LOG" 2>&1; then
  say "preflight gate closed: no GEPA, no dry run; stopping the pod"
  export RUNPOD_API_KEY="$(tr '\0' '\n' < /proc/1/environ | grep '^RUNPOD_API_KEY=' | cut -d= -f2-)"
  runpodctl stop pod "$(tr '\0' '\n' < /proc/1/environ | grep '^RUNPOD_POD_ID=' | cut -d= -f2)" >> "$LOG" 2>&1
  exit 1
fi
say "setup healthy; GEPA pilot"
bash scripts/run_job.sh --no-stop --wait gepa_pilot python -m scripts.chunk4 gepa --thinking off >> "$LOG" 2>&1
say "GEPA pilot ended; chunk 5 dry run (stops the pod at its end)"
bash scripts/run_job.sh --wait chunk5_dryrun python -m scripts.chunk5_job --dry-run >> "$LOG" 2>&1
say "queue done"
