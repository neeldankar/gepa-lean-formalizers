"""The chunk 5 combined job: dry-run plan, sanity check, and a dry-run final eval that never touches held-out data."""
import copy
import json

import pytest

from scripts import chunk5_job
from src import final_eval
from src.axle_check import AxleChecker
from src.config import ROOT, load_config
from src.llm import LLMClient
from src.mocks import MockAxleClient, MockPosts

CFG = load_config()
SPLITS = json.loads((ROOT / "data/splits.json").read_text())


def test_real_plan_runs_all_six_into_runs():
    plan = chunk5_job.job_plan(CFG, dry=False)
    assert plan["run_ids"] == list(CFG["gepa"]["runs"]) and len(plan["run_ids"]) == 6
    assert plan["runs_dir"] == "runs" and plan["chunk"] == 5 and plan["standin_ids"] is None


def test_dry_plan_uses_train_standins_and_its_own_dir():
    plan = chunk5_job.job_plan(CFG, dry=True)
    ids = set(plan["standin_ids"])
    assert len(ids) == 5 and ids <= set(SPLITS["train"]) and not ids & set(CFG["fewshot"]["ids"])
    assert not ids & (set(SPLITS["test"]) | set(SPLITS["val"]))
    assert plan["runs_dir"] == "runs/dryrun_chunk5" and plan["run_ids"] == ["B_s0", "D_s0"] and plan["chunk"] == 4
    cfg = chunk5_job.job_cfg(CFG, plan)
    assert cfg["arms"]["B"]["gepa_runs"] == ["B_s0"] and cfg["arms"]["D"]["gepa_runs"] == ["D_s0"]
    assert cfg["gepa"]["runs"]["B_s0"]["max_metric_calls"] == 10 and cfg["gepa"]["runs"]["B_s0"]["val_limit"] == 5
    assert CFG["gepa"]["runs"]["B_s0"].get("val_limit") is None  # the real config is untouched


def fake_run(d, calls=150, stopped=False, prompt="Keep every hypothesis.", candidates=True):
    d.mkdir(parents=True)
    (d / "candidates.json").write_text(json.dumps({"total_metric_calls": calls}))
    (d / "best_prompt.txt").write_text(prompt + "\n")
    if candidates:
        (d / "candidates").mkdir()
        (d / "candidates/abc.jsonl").write_text("{}\n")
    (d / ("STOPPED" if stopped else "DONE")).write_text("x\n")


def test_sanity_check(tmp_path):
    cfg = copy.deepcopy(CFG)
    cfg["gepa"]["max_metric_calls"] = 150
    ids = list(cfg["gepa"]["runs"])
    for r in ids:
        fake_run(tmp_path / "ok" / r)
    assert chunk5_job.sanity_check(cfg, tmp_path / "ok", ids) == []
    fake_run(tmp_path / "bad" / ids[0], stopped=True)
    fake_run(tmp_path / "bad" / ids[1], calls=150 + 3 + 70 + 1)
    fake_run(tmp_path / "bad" / ids[2], prompt="  ")
    fake_run(tmp_path / "bad" / ids[3], candidates=False)
    for r in ids[4:]:
        fake_run(tmp_path / "bad" / r)
    problems = chunk5_job.sanity_check(cfg, tmp_path / "bad", ids)
    assert len(problems) == 5  # STOPPED and no DONE, too many calls, empty prompt, no candidates
    assert any("STOPPED" in p for p in problems) and any("metric calls" in p for p in problems)


def test_dry_run_eval_never_touches_test_or_minif2f(tmp_path, monkeypatch):
    def forbidden(*a, **k):
        raise AssertionError("the dry run loaded held-out data")
    monkeypatch.setattr(final_eval, "heldout_items", forbidden)
    plan = chunk5_job.job_plan(CFG, dry=True)
    cfg = chunk5_job.job_cfg(CFG, plan)
    cfg["axle"]["outage_backoff_seconds"] = 0
    runs = tmp_path / "runs/dryrun_chunk5"
    for r in plan["run_ids"]:
        (runs / r).mkdir(parents=True)
        (runs / r / "best_prompt.txt").write_text("Keep every hypothesis from the problem.\n")
    posts = MockPosts()
    kw = dict(cache_dir=tmp_path / "llm", costs_path=tmp_path / "costs.jsonl")
    gen = LLMClient(cfg, 4, post=posts.formalizer, base_url="http://mock", api_key_env=None, **kw)
    judge = LLMClient(cfg, 4, post=posts.judge, **kw)
    checker = AxleChecker(cfg["axle"], client_factory=MockAxleClient, cache_dir=tmp_path / "axle")
    loader = chunk5_job.standin_loader(plan)
    for arm in cfg["arms"]:
        rows = final_eval.eval_arm(cfg, arm, gen, judge, checker, runs, ROOT, items_for=loader)
        assert {r["item_id"] for r in rows} == set(plan["standin_ids"])
        assert {r["dataset"] for r in rows} <= {"dryrun_test", "dryrun_minif2f"}
        want = 1 if arm == "F" else 2
        assert len({r["dataset"] for r in rows}) == want
        if arm in ("B", "D"):
            assert {r["run_id"] for r in rows} == {f"{arm}_s0"}


def test_final_eval_failure_is_reported_not_skipped(tmp_path, monkeypatch):
    from src.llm import LLMError
    calls = []
    def eval_arm(cfg, arm, *a, **k):
        calls.append(arm)
        if arm == "C":
            raise LLMError("gave up after 2 attempts: no reply within 1800 s")
        return [{"dataset": "dryrun_test", "item_id": "pnv_x", "outage": False}]
    monkeypatch.setattr(chunk5_job, "eval_arm", eval_arm)
    monkeypatch.setattr(chunk5_job, "write_rows", lambda path, rows: None)
    plan = chunk5_job.job_plan(CFG, dry=True)
    saved = {}
    rows, outages, error = chunk5_job.run_final(chunk5_job.job_cfg(CFG, plan), plan, tmp_path, tmp_path / "final", saved.update)
    assert error.startswith("arm C: LLMError: gave up") and list(rows) == ["A", "B"] and calls == ["A", "B", "C"]


def test_done_runs_are_skipped_and_still_sanity_checked(tmp_path, monkeypatch):
    # GEPA 0.1.4 re-evaluates the seed on the full val set before loading its state, so a DONE run must not restart.
    started = []

    class FakeChild:
        returncode = 0
        def poll(self):
            return 0

    def popen(cmd, **kw):
        started.append(cmd[cmd.index("scripts.gepa_run") + 1])
        return FakeChild()

    class NoMeter:
        def __init__(self, *a, **k):
            pass
        def tick(self):
            pass

    monkeypatch.setattr(chunk5_job.subprocess, "Popen", popen)
    monkeypatch.setattr(chunk5_job, "GpuMeter", NoMeter)
    ids = list(CFG["gepa"]["runs"])
    fake_run(tmp_path / ids[0])  # finished: has DONE
    plan = {"chunk": 5, "runs_dir": str(tmp_path), "run_ids": ids, "override": {}, "standin_ids": None, "poll_seconds": 0}
    codes = chunk5_job.run_gepa_children(CFG, plan, tmp_path / "logs")
    assert started == ids[1:] and codes[ids[0]] == "skipped (done)" and all(codes[r] == 0 for r in ids[1:])
    assert chunk5_job.sanity_check(CFG, tmp_path, ids[:1]) == []  # the skipped run is still checked
    (tmp_path / ids[0] / "best_prompt.txt").write_text(" ")
    assert chunk5_job.sanity_check(CFG, tmp_path, ids[:1]) != []


def test_saved_candidate_outputs_are_never_overwritten(tmp_path):
    from src.gepa_adapter import FormalizerAdapter
    adapter = object.__new__(FormalizerAdapter)
    adapter.candidates_dir = tmp_path
    row = {"item_id": "pnv_1", "sample": 0, "output": "first", "extracted": None, "compile_status": "ok", "compiled": True,
           "lean_errors": [], "judge": {"verdict": "faithful", "reason": ""}, "score": 1}
    adapter.save_candidate("same prompt", [row])
    adapter.save_candidate("same prompt", [{**row, "output": "re-evaluated on resume"}])
    (path,) = tmp_path.glob("*.jsonl")
    assert json.loads(path.read_text().splitlines()[1])["output"] == "first"
