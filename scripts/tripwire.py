"""Chunk 5 tripwire (Neel, 2026-10-22): if reflection attempts start failing (3 or more failed attempts
within 15 minutes), pause every GEPA run cleanly before any run uses up its retries and stops for good.

Usage on the pod, in its own tmux session next to the job:
  python -m scripts.tripwire --since ISO_TIME [--session chunk5]

Pause: kill the job's tmux session first (so run_job.sh neither pushes nor stops the pod), then the job and
its GEPA children. GEPA saves its state after every iteration, so a resume loses at most the iteration in
progress; no STOPPED or DONE marker is written. Then it writes /workspace/TRIPWIRE (the reason), pushes
runs/, and waits 30 minutes for Neel: if /workspace/KEEP_POD appears it leaves the pod up, otherwise it
stops the pod (Neel's rule: stop if idle more than about 30 min waiting on him). It exits on its own when
the job's tmux session ends without a trip.
"""
import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.config import ROOT, load_config, load_env
from src.costs import GpuMeter
from src.llm import FAILURES_PATH

THRESHOLD = 3
WINDOW = timedelta(minutes=15)
POLL_SECONDS = 30
WAIT_FOR_NEEL = 30 * 60
WORK = Path("/workspace")
JOB_PATTERN = r"scripts\.chunk5_job|scripts\.gepa_run"


def recent_failures(rows, now, since, window=WINDOW):
    """Failed reflection attempts after `since` and inside the last `window`."""
    start = max(since, now - window)
    return [r for r in rows if r.get("purpose") == "reflection" and datetime.fromisoformat(r["time"]) >= start]


def should_trip(rows, now, since, threshold=THRESHOLD, window=WINDOW):
    return len(recent_failures(rows, now, since, window)) >= threshold


def read_failures(path=FAILURES_PATH):
    if not Path(path).exists():
        return []
    return [json.loads(l) for l in open(path) if l.strip()]


def session_alive(session, run=subprocess.run):
    return run(["tmux", "has-session", "-t", session], capture_output=True).returncode == 0


def pause(session, run=subprocess.run, kill=os.kill, sleep=time.sleep):
    """Kill the tmux session first, then every job and GEPA process (TERM, then KILL after 30 s)."""
    run(["tmux", "kill-session", "-t", session], capture_output=True)
    pids = lambda: [int(p) for p in run(["pgrep", "-f", JOB_PATTERN], capture_output=True, text=True).stdout.split()]
    for pid in pids():
        kill(pid, signal.SIGTERM)
    for _ in range(30):
        if not pids():
            return []
        sleep(1)
    left = pids()
    for pid in left:
        kill(pid, signal.SIGKILL)
    return left


def push(message, run=subprocess.run):
    """Commit runs/ and push, the way run_job.sh does; the token is never printed."""
    load_env()
    remote = f"https://x-access-token:{os.environ['GITHUB_TOKEN']}@github.com/neeldankar/gepa-lean-formalizers.git"
    run(["git", "add", "runs/"], cwd=ROOT)
    run(["git", "commit", "-q", "-m", message], cwd=ROOT)
    run(["git", "pull", "-q", "--rebase", remote, "main"], cwd=ROOT, capture_output=True)
    if run([sys.executable, "scripts/secret_scan.py", "--history"], cwd=ROOT).returncode == 0:
        run(["git", "push", "-q", remote, "HEAD:main"], cwd=ROOT, capture_output=True)


def stop_pod(run=subprocess.run):
    env = dict(l.split("=", 1) for l in Path("/proc/1/environ").read_text().split("\0") if "=" in l)
    run(["runpodctl", "stop", "pod", env["RUNPOD_POD_ID"]], env={**os.environ, "RUNPOD_API_KEY": env["RUNPOD_API_KEY"]})


def trip(failures, session, work=WORK, run=subprocess.run, kill=os.kill, sleep=time.sleep, wait=WAIT_FOR_NEEL,
         meter=None, push=push, stop_pod=stop_pod):
    """Pause, record why, push, then wait for Neel before stopping the pod."""
    left = pause(session, run=run, kill=kill, sleep=sleep)
    now = datetime.now(timezone.utc)
    reason = {"time": now.isoformat(timespec="seconds"), "rule": f"{THRESHOLD}+ failed reflection attempts in {WINDOW}",
              "failures": [{k: r.get(k) for k in ("time", "run_id", "kind", "seconds", "error")} for r in failures],
              "killed_with_sigkill": left, "action": "paused; GEPA state kept; no STOPPED or DONE written"}
    (work / "TRIPWIRE").write_text(json.dumps(reason, indent=1) + "\n")
    (ROOT / "runs/chunk5").mkdir(parents=True, exist_ok=True)
    (ROOT / "runs/chunk5/tripwire.json").write_text(json.dumps(reason, indent=1) + "\n")
    push(f"TRIPWIRE: chunk 5 paused, {len(failures)} failed reflection attempts in 15 min")
    meter = meter or GpuMeter(load_config(), 5, "tripwire_wait")  # the job's meter died with the job
    waited = 0
    while waited < wait and not (work / "KEEP_POD").exists():
        sleep(POLL_SECONDS)
        waited += POLL_SECONDS
    meter.tick()
    if (work / "KEEP_POD").exists():
        return "kept"
    push("Tripwire: no answer in 30 min; stopping the pod")
    stop_pod()
    return "stopped"


def main(argv):
    since = datetime.fromisoformat(argv[argv.index("--since") + 1])
    session = argv[argv.index("--session") + 1] if "--session" in argv else "chunk5"
    print(f"tripwire armed: {THRESHOLD}+ failed reflection attempts in {WINDOW}, since {since.isoformat()}", flush=True)
    while session_alive(session):
        now = datetime.now(timezone.utc)
        failures = recent_failures(read_failures(), now, since)
        if len(failures) >= THRESHOLD:
            print(f"tripped at {now.isoformat(timespec='seconds')}: {len(failures)} failed attempts", flush=True)
            print(trip(failures, session), flush=True)
            return
        time.sleep(POLL_SECONDS)
    print("job session ended without a trip", flush=True)


if __name__ == "__main__":
    main(sys.argv[1:])
