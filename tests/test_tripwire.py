"""The chunk 5 tripwire: 3+ failed reflection attempts in 15 minutes pause every run cleanly."""
import json
import signal
from datetime import datetime, timedelta, timezone

from scripts import tripwire

SINCE = datetime(2026, 10, 22, 19, 0, tzinfo=timezone.utc)


def fail(minutes, purpose="reflection"):
    return {"time": (SINCE + timedelta(minutes=minutes)).isoformat(timespec="seconds"), "purpose": purpose,
            "run_id": "B_s0", "kind": "RetryableError", "seconds": 340.0, "error": "HTTP 503"}


def test_three_failures_in_fifteen_minutes_trip():
    now = SINCE + timedelta(minutes=30)
    assert not tripwire.should_trip([fail(20), fail(25)], now, SINCE)
    assert tripwire.should_trip([fail(16), fail(20), fail(29)], now, SINCE)


def test_failures_spread_out_or_old_or_not_reflection_do_not_trip():
    now = SINCE + timedelta(minutes=30)
    assert not tripwire.should_trip([fail(1), fail(10), fail(29)], now, SINCE)  # only one inside the last 15 min
    assert not tripwire.should_trip([fail(-5), fail(-3), fail(20), fail(25)], SINCE + timedelta(minutes=10), SINCE + timedelta(minutes=0))
    assert not tripwire.should_trip([fail(20, "generate"), fail(21, "generate"), fail(22, "ref_judge")], now, SINCE)


class FakeRun:
    """Records commands; pgrep reports the given pids until they get SIGTERM."""

    def __init__(self, pids, survivors=()):
        self.calls, self.alive, self.survivors = [], set(pids), set(survivors)

    def __call__(self, cmd, **kw):
        self.calls.append(cmd)
        out = " ".join(map(str, sorted(self.alive))) if cmd[0] == "pgrep" else ""
        return type("R", (), {"returncode": 0, "stdout": out})()

    def kill(self, pid, sig):
        self.calls.append(["kill", pid, sig])
        if sig == signal.SIGKILL or pid not in self.survivors:
            self.alive.discard(pid)


def test_pause_kills_the_tmux_session_first_then_the_processes():
    run = FakeRun([101, 102])
    assert tripwire.pause("chunk5", run=run, kill=run.kill, sleep=lambda s: None) == []
    assert run.calls[0] == ["tmux", "kill-session", "-t", "chunk5"]  # before any job process dies
    assert ["kill", 101, signal.SIGTERM] in run.calls and ["kill", 102, signal.SIGTERM] in run.calls
    assert not any(c[0] == "kill" and c[2] == signal.SIGKILL for c in run.calls if c[0] == "kill")


def test_pause_uses_sigkill_only_on_survivors():
    run = FakeRun([101, 102], survivors=[102])
    assert tripwire.pause("chunk5", run=run, kill=run.kill, sleep=lambda s: None) == [102]
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

    out = tripwire.trip([fail(20), fail(21), fail(22)], "chunk5", work=tmp_path, run=run, kill=run.kill, sleep=sleep,
                        wait=600, meter=Meter(), push=pushes.append, stop_pod=lambda: stops.append(1))
    return out, pushes, stops, run


def test_trip_records_why_pushes_and_stops_the_pod_if_no_answer(tmp_path, monkeypatch):
    out, pushes, stops, run = run_trip(tmp_path, monkeypatch, keep=False)
    assert out == "stopped" and stops == [1] and len(pushes) == 2 and pushes[0].startswith("TRIPWIRE")
    reason = json.loads((tmp_path / "TRIPWIRE").read_text())
    assert len(reason["failures"]) == 3 and "no STOPPED or DONE" in reason["action"]
    assert json.loads((tmp_path / "runs/chunk5/tripwire.json").read_text()) == reason
    assert run.calls[0][:2] == ["tmux", "kill-session"]


def test_trip_keeps_the_pod_when_neel_answers(tmp_path, monkeypatch):
    out, pushes, stops, _ = run_trip(tmp_path, monkeypatch, keep=True)
    assert out == "kept" and stops == [] and len(pushes) == 1


def test_trip_writes_no_run_markers(tmp_path, monkeypatch):
    run_trip(tmp_path, monkeypatch, keep=False)
    assert not list(tmp_path.rglob("STOPPED")) and not list(tmp_path.rglob("DONE"))
