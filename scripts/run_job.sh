#!/bin/bash
# Run a long job on the pod inside tmux, then push its results and stop the pod.
# Usage: bash scripts/run_job.sh [--dry-run] JOB_NAME COMMAND...
#   e.g. bash scripts/run_job.sh gepa_B_s0 python -m scripts.gepa_run B_s0
# Needs GITHUB_TOKEN in .env (loaded; nothing is printed). The pod id and RUNPOD_API_KEY come from the
# container (RUNPOD_POD_ID in .env is only a fallback).
set -euo pipefail
cd "$(dirname "$0")/.."

DRY=0; STOP=1; WAIT=0
while [ "${1:-}" != "" ] && [ "${1#--}" != "$1" ]; do
  case "$1" in
    --dry-run) DRY=1 ;;
    --no-stop) STOP=0 ;;   # push results but keep the pod running (a later job in the same queue stops it)
    --wait) WAIT=1 ;;      # block until the job ends (to chain jobs in one queue)
    *) echo "unknown option $1" >&2; exit 2 ;;
  esac
  shift
done
JOB=$1; shift
CMD="$*"
VENV=${VENV:-/workspace/venv}
[ -x "$VENV/bin/python" ] && export PATH="$VENV/bin:$PATH"
PY=${PYTHON:-python3}
WORK=$("$PY" -c "import yaml; print(yaml.safe_load(open('config.yaml'))['pod']['workdir'])")
LOG="$WORK/logs/$JOB.log"

# The body that runs inside tmux. Results are pushed even when the job fails, then the pod stops.
read -r -d '' BODY <<SCRIPT || true
set -o pipefail
cd "$(pwd)"
[ -x "$VENV/bin/python" ] && export PATH="$VENV/bin:\$PATH"
set -a; [ -f .env ] && . ./.env; set +a
mkdir -p "$WORK/logs"
echo "[\$(date -u +%FT%TZ)] start $JOB: $CMD" >> "$LOG"
$CMD >> "$LOG" 2>&1; STATUS=\$?
echo "[\$(date -u +%FT%TZ)] end $JOB: exit \$STATUS" >> "$LOG"
cp "$LOG" "runs/logs_$JOB.log" 2>/dev/null || true
git add runs/ && git commit -q -m "Results: $JOB (exit \$STATUS)" || true
REMOTE="https://x-access-token:\${GITHUB_TOKEN}@github.com/neeldankar/gepa-lean-formalizers.git"
git pull -q --rebase "\$REMOTE" main 2>&1 | sed "s/x-access-token:[^@]*@/***@/g"   # the laptop may have pushed meanwhile
python3 scripts/secret_scan.py --history && git push -q "\$REMOTE" HEAD:main 2>&1 | sed "s/x-access-token:[^@]*@/***@/g"
# runpodctl needs RUNPOD_API_KEY, which RunPod sets only in the container's own environment (PID 1),
# not in SSH or tmux shells; read it from there without printing it. The pod id comes from there too:
# a new pod gets a new id, and the one in .env may be an old pod's.
if [ "$STOP" = 1 ]; then
[ -z "\${RUNPOD_API_KEY:-}" ] && export RUNPOD_API_KEY="\$(tr '\\0' '\\n' < /proc/1/environ | grep '^RUNPOD_API_KEY=' | cut -d= -f2-)"
SELF_POD="\$(tr '\\0' '\\n' < /proc/1/environ | grep '^RUNPOD_POD_ID=' | cut -d= -f2)"
runpodctl stop pod "\${SELF_POD:-\$RUNPOD_POD_ID}"
fi
SCRIPT

if [ "$DRY" = 1 ]; then
  echo "+ tmux new-session -d -s $JOB bash -c <body>"
  echo "$BODY"
  exit 0
fi
tmux new-session -d -s "$JOB" bash -c "$BODY"
echo "started tmux session $JOB; log: $LOG"
if [ "$WAIT" = 1 ]; then
  while tmux has-session -t "$JOB" 2>/dev/null; do sleep 30; done
  echo "tmux session $JOB ended"
fi
