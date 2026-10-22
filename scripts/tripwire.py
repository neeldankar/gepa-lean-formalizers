"""Chunk 5 tripwire (Neel, 2026-10-22): pause every GEPA run cleanly when Kimi-K3 looks down provider-wide.
It trips when (a) failed reflection attempts come from 2 or more different runs within 15 minutes, or (b) any
single reflection call ends in failure (its retries used up, or an error not worth retrying). One unlucky call
retrying in one run is not an outage: the first rule (3+ failed attempts in 15 min, any runs) tripped pod 7
on three ~300 s stalls of a single D_s2 call that then completed on a plain retry.

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

from scripts.chunk5_job import push
from src.config import ROOT, load_config
from src.costs import GpuMeter
from src.llm import FAILURES_PATH

MIN_RUNS = 2
WINDOW = timedelta(minutes=15)
POLL_SECONDS = 30
WAIT_FOR_NEEL = 30 * 60
WORK = Path("/workspace")
JOB_MODULES = ("scripts.chunk5_job", "scripts.gepa_run")


def recent_failures(rows, now, since, window=WINDOW):
    """Failed reflection attempts after `since` and inside the last `window`."""
    start = max(since, now - window)
    return [r for r in rows if r.get("purpose") == "reflection" and datetime.fromisoformat(r["time"]) >= start]


def trip_reason(rows, now, since, window=WINDOW):
    """(rule, failures) when the tripwire should trip, else None."""
    recent = recent_failures(rows, now, since, window)
    final = [r for r in recent_failures(rows, now, since, now - since) if r.get("final")]
    if final:
        return "a reflection call failed for good (retries used up or not retryable)", final
    if len({r.get("run_id") for r in recent}) >= MIN_RUNS:
        return f"failed reflection attempts in {MIN_RUNS}+ different runs within {WINDOW}", recent
    return None


def should_trip(rows, now, since, window=WINDOW):
    return trip_reason(rows, now, since, window) is not None


def read_failures(path=FAILURES_PATH):
    if not Path(path).exists():
        return []
    return [json.loads(l) for l in open(path) if l.strip()]


def session_alive(session, run=subprocess.run):
    return run(["tmux", "has-session", "-t", session], capture_output=True).returncode == 0


def proc_cmdlines(root=Path("/proc")):
    """{pid: argv} for every process we can read."""
    out = {}
    for d in root.iterdir():
        if d.name.isdigit():
            try:
                out[int(d.name)] = (d / "cmdline").read_bytes().decode(errors="replace").split("\0")
            except OSError:
                continue
    return out


def job_pids(cmdlines, me=None):
    """Python processes running `-m scripts.chunk5_job` or `-m scripts.gepa_run`, and nothing else: a text
    match (pgrep -f) also hits the tmux server, whose argv holds run_job.sh's command, and killing it takes
    every tmux session down, this tripwire's included (pod 7, 2026-10-22)."""
    pids = []
    for pid, argv in cmdlines.items():
        if pid == me or not argv or not Path(argv[0]).name.startswith("python"):
            continue
        if any(a == "-m" and b in JOB_MODULES for a, b in zip(argv, argv[1:])):
            pids.append(pid)
    return sorted(pids)


def pause(session, run=subprocess.run, kill=os.kill, sleep=time.sleep, cmdlines=None):
    """Kill the tmux session first, then every job and GEPA process (TERM, then KILL after 30 s)."""
    run(["tmux", "kill-session", "-t", session], capture_output=True)
    cmdlines = cmdlines or proc_cmdlines
    pids = lambda: job_pids(cmdlines(), me=os.getpid())
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


def stop_pod(run=subprocess.run):
    env = dict(l.split("=", 1) for l in Path("/proc/1/environ").read_text().split("\0") if "=" in l)
    run(["runpodctl", "stop", "pod", env["RUNPOD_POD_ID"]], env={**os.environ, "RUNPOD_API_KEY": env["RUNPOD_API_KEY"]})


def trip(rule, failures, session, work=WORK, run=subprocess.run, kill=os.kill, sleep=time.sleep, wait=WAIT_FOR_NEEL,
         meter=None, push=push, stop_pod=stop_pod):
    """Pause, record why, push, then wait for Neel before stopping the pod."""
    left = pause(session, run=run, kill=kill, sleep=sleep)
    now = datetime.now(timezone.utc)
    reason = {"time": now.isoformat(timespec="seconds"), "rule": rule,
              "failures": [{k: r.get(k) for k in ("time", "run_id", "kind", "seconds", "error")} for r in failures],
              "killed_with_sigkill": left, "action": "paused; GEPA state kept; no STOPPED or DONE written"}
    (work / "TRIPWIRE").write_text(json.dumps(reason, indent=1) + "\n")
    (ROOT / "runs/chunk5").mkdir(parents=True, exist_ok=True)
    (ROOT / "runs/chunk5/tripwire.json").write_text(json.dumps(reason, indent=1) + "\n")
    push(f"TRIPWIRE: chunk 5 paused: {rule}")
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
    print(f"tripwire armed: failed reflection attempts in {MIN_RUNS}+ runs within {WINDOW}, or one reflection call"
          f" failed for good; since {since.isoformat()}", flush=True)
    while session_alive(session):
        now = datetime.now(timezone.utc)
        reason = trip_reason(read_failures(), now, since)
        if reason:
            print(f"tripped at {now.isoformat(timespec='seconds')}: {reason[0]}", flush=True)
            print(trip(*reason, session), flush=True)
            return
        time.sleep(POLL_SECONDS)
    print("job session ended without a trip", flush=True)


if __name__ == "__main__":
    main(sys.argv[1:])
