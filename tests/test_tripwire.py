"""The chunk 5 tripwire: failed reflection attempts in 2+ runs within 15 minutes, or one reflection call failed
for good, pause every run cleanly."""
import json
import signal
from datetime import datetime, timedelta, timezone

from scripts import tripwire

SINCE = datetime(2026, 10, 22, 19, 0, tzinfo=timezone.utc)


def fail(minutes, purpose="reflection", run_id="B_s0", attempt=0, final=False):
    return {"time": (SINCE + timedelta(minutes=minutes)).isoformat(timespec="seconds"), "purpose": purpose,
            "run_id": run_id, "kind": "RetryableError", "seconds": 340.0, "error": "HTTP 503",
            "attempt": attempt, "final": final}


def test_one_call_retrying_in_one_run_does_not_trip():
    # Pod 7, 20:43 UTC: one D_s2 call stalled ~300 s on 3 attempts, and the same request later completed
    now = SINCE + timedelta(minutes=30)
    stalls = [fail(16, run_id="D_s2", attempt=0), fail(21.5, run_id="D_s2", attempt=1), fail(27.5, run_id="D_s2", attempt=2)]
    assert not tripwire.should_trip(stalls, now, SINCE)
    assert not tripwire.should_trip(stalls + [fail(28.5, run_id="D_s2", attempt=3)], now, SINCE)


def test_failures_in_two_runs_within_fifteen_minutes_trip():
    now = SINCE + timedelta(minutes=30)
    rule, failures = tripwire.trip_reason([fail(20, run_id="D_s2"), fail(25, run_id="B_s1")], now, SINCE)
    assert "2+ different runs" in rule and len(failures) == 2
    assert not tripwire.should_trip([fail(5, run_id="D_s2"), fail(25, run_id="B_s1")], now, SINCE)  # 20 min apart


def test_a_call_that_used_up_its_retries_trips_even_alone():
    now = SINCE + timedelta(minutes=60)
    rows = [fail(10 + i, run_id="D_s2", attempt=i, final=i == 4) for i in range(5)]
    rule, failures = tripwire.trip_reason(rows, now, SINCE)  # the last attempt is 46 min old: still trips
    assert "for good" in rule and [r["attempt"] for r in failures] == [4]


def test_failures_old_or_not_reflection_do_not_trip():
    now = SINCE + timedelta(minutes=30)
    assert not tripwire.should_trip([fail(-5, run_id="D_s2", final=True), fail(-3, run_id="B_s1")], now, SINCE)
    assert not tripwire.should_trip([fail(20, "generate", "final_F", final=True), fail(21, "ref_judge", "final")], now, SINCE)
    assert not tripwire.should_trip([{k: v for k, v in fail(20).items() if k != "final"}], now, SINCE)  # rows before the field


class FakeRun:
    """Records commands; the fake /proc lists the given pids until they get SIGTERM."""

    def __init__(self, pids, survivors=()):
        self.calls, self.alive, self.survivors = [], set(pids), set(survivors)

    def __call__(self, cmd, **kw):
        self.calls.append(cmd)
        return type("R", (), {"returncode": 0, "stdout": ""})()

    def cmdlines(self):
        procs = {p: ["/workspace/venv/bin/python", "-m", "scripts.gepa_run", "B_s0"] for p in self.alive}
        procs[1] = ["tmux", "new-session", "-d", "-s", "chunk5", "bash", "-c", "python -m scripts.chunk5_job"]
        return procs

    def kill(self, pid, sig):
        self.calls.append(["kill", pid, sig])
        if sig == signal.SIGKILL or pid not in self.survivors:
            self.alive.discard(pid)


def test_pause_kills_the_tmux_session_first_then_the_processes():
    run = FakeRun([101, 102])
    assert tripwire.pause("chunk5", run=run, kill=run.kill, sleep=lambda s: None, cmdlines=run.cmdlines) == []
    assert run.calls[0] == ["tmux", "kill-session", "-t", "chunk5"]  # before any job process dies
    assert ["kill", 101, signal.SIGTERM] in run.calls and ["kill", 102, signal.SIGTERM] in run.calls
    assert not any(c[0] == "kill" and c[2] == signal.SIGKILL for c in run.calls if c[0] == "kill")


def test_pause_uses_sigkill_only_on_survivors():
    run = FakeRun([101, 102], survivors=[102])
    assert tripwire.pause("chunk5", run=run, kill=run.kill, sleep=lambda s: None, cmdlines=run.cmdlines) == [102]
    assert ["kill", 102, signal.SIGKILL] in run.calls and ["kill", 101, signal.SIGKILL] not in run.calls


class Meter:
    ticks = 0

    def tick(self):
        Meter.ticks += 1


def run_trip(tmp_path, monkeypatch, keep):
    monkeypatch.setattr(tripwire, "ROOT", tmp_path)
    pushes, stops = [], []
    run = FakeRun([101])
    sleeps = []

    def sleep(s):
        sleeps.append(s)
        if keep and len(sleeps) == 10:  # Neel answers 5 min into the 10 min wait
            (tmp_path / "KEEP_POD").write_text("")

    monkeypatch.setattr(tripwire, "proc_cmdlines", run.cmdlines)
    out = tripwire.trip("rule", [fail(20), fail(21), fail(22)], "chunk5", work=tmp_path, run=run, kill=run.kill, sleep=sleep,
                        wait=600, meter=Meter(), push=pushes.append, stop_pod=lambda: stops.append(1))
    return out, pushes, stops, run


def test_trip_records_why_pushes_and_stops_the_pod_if_no_answer(tmp_path, monkeypatch):
    out, pushes, stops, run = run_trip(tmp_path, monkeypatch, keep=False)
    assert out == "stopped" and stops == [1] and len(pushes) == 2 and pushes[0].startswith("TRIPWIRE") and "rule" in pushes[0]
    reason = json.loads((tmp_path / "TRIPWIRE").read_text())
    assert reason["rule"] == "rule" and len(reason["failures"]) == 3 and "no STOPPED or DONE" in reason["action"]
    assert json.loads((tmp_path / "runs/chunk5/tripwire.json").read_text()) == reason
    assert run.calls[0][:2] == ["tmux", "kill-session"]


def test_trip_keeps_the_pod_when_neel_answers(tmp_path, monkeypatch):
    out, pushes, stops, _ = run_trip(tmp_path, monkeypatch, keep=True)
    assert out == "kept" and stops == [] and len(pushes) == 1


def test_trip_writes_no_run_markers(tmp_path, monkeypatch):
    run_trip(tmp_path, monkeypatch, keep=False)
    assert not list(tmp_path.rglob("STOPPED")) and not list(tmp_path.rglob("DONE"))


def test_only_python_job_processes_are_killed_never_tmux_or_the_tripwire():
    # Pod 7: pgrep -f matched the tmux server (its argv holds run_job.sh's command) and the pause killed
    # every tmux session, the tripwire's own included, before it could record or push anything.
    procs = {
        1: ["tmux", "new-session", "-d", "-s", "chunk5", "bash", "-c", "python -m scripts.chunk5_job >> log"],
        2: ["bash", "-c", "set -o pipefail\npython -m scripts.chunk5_job >> log"],
        3: ["python", "-m", "scripts.chunk5_job"],
        4: ["/workspace/venv/bin/python", "-m", "scripts.gepa_run", "D_s2", "--chunk", "5"],
        5: ["/workspace/venv/bin/python", "-m", "scripts.tripwire", "--since", "x"],
        6: ["vllm", "serve", "Qwen/Qwen3-8B"],
        7: ["python3", "/workspace/watch.py", "scripts.gepa_run"],
    }
    assert tripwire.job_pids(procs, me=5) == [3, 4]
    assert tripwire.job_pids(procs, me=3) == [4]
