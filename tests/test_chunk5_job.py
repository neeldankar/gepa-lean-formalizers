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


def final_with(monkeypatch, tmp_path, dry):
    order, pushes = [], []
    def eval_arm(cfg, arm, *a, **k):
        order.append(arm)
        return [{"dataset": "test", "item_id": "pnv_x", "outage": False, "generation_missing": arm == "F"}]
    monkeypatch.setattr(chunk5_job, "eval_arm", eval_arm)
    monkeypatch.setattr(chunk5_job, "write_rows", lambda path, rows: order.append(f"wrote {path.name}"))
    plan = chunk5_job.job_plan(CFG, dry=dry)
    def push(message):
        pushes.append((message, list(order)))
        return "pushed"
    saved = {}
    rows, _, error = chunk5_job.run_final(chunk5_job.job_cfg(CFG, plan), plan, tmp_path, tmp_path / "final", saved.update, push=push)
    return order, pushes, rows, error, saved


def test_arm_f_runs_last_after_the_other_arms_are_written_and_pushed(tmp_path, monkeypatch):
    # Deviation 3. The real plan: monkeypatched eval_arm, so nothing held out is loaded.
    order, pushes, rows, error, saved = final_with(monkeypatch, tmp_path, dry=False)
    assert error is None and [a for a in order if len(a) == 1] == ["A", "B", "C", "D", "E", "F"]
    assert len(pushes) == 1 and pushes[0][1][-1] == "wrote E.jsonl.gz" and "F" not in pushes[0][1]
    assert saved["push_before_last_arms"] == "pushed"
    assert rows["F"]["missing_generation"] == 1 and rows["A"]["missing_generation"] == 0


def test_dry_run_never_pushes(tmp_path, monkeypatch):
    order, pushes, rows, error, _ = final_with(monkeypatch, tmp_path, dry=True)
    assert error is None and pushes == [] and order[-2:] == ["F", "wrote F.jsonl.gz"]


def fake_row(arm, run_id, dataset, item_id, **kw):
    row = {"arm": arm, "run_id": run_id, "gepa_seed": None, "dataset": dataset, "item_id": item_id, "sample": 0,
           "format_failure": False, "compile_status": "ok", "compiled": True, "judge_score": 1, "judge_missing": False,
           "certified": False, "ref_missing": False, "truth_label": "faithful", "truth_source": "ref_judge",
           "outage": False, "generation_missing": False}
    return {**row, **kw}


EXPECTED = {"test": {"t1", "t2"}, "minif2f": {"m1"}}


def full_rows(arm, run_ids=(None,), datasets=("test", "minif2f")):
    return [fake_row(arm, r, ds, i) for r in run_ids for ds in datasets for i in sorted(EXPECTED[ds])]


def test_arm_health_passes_clean_rows():
    assert chunk5_job.arm_health(CFG, "A", full_rows("A"), EXPECTED)["pass"]
    b = chunk5_job.arm_health(CFG, "B", full_rows("B", CFG["arms"]["B"]["gepa_runs"]), EXPECTED)
    assert b["pass"] and set(b["counts_per_run"]) == set(CFG["arms"]["B"]["gepa_runs"])
    assert chunk5_job.arm_health(CFG, "F", full_rows("F", datasets=("test",)), EXPECTED)["pass"]


def test_faithful_without_compiling_fails():
    for bad in ({"judge_score": 1, "truth_label": "unfaithful"}, {"judge_score": 0, "truth_label": "faithful"},
                {"judge_score": 0, "truth_label": "unfaithful", "certified": True}):
        rows = full_rows("A")
        rows[0].update(compiled=False, compile_status="lean_error", **bad)
        h = chunk5_job.arm_health(CFG, "A", rows, EXPECTED)
        assert not h["pass"] and sum(h["violations"].values()) == 1


def test_duplicates_missing_and_extra_ids_fail():
    rows = full_rows("A")
    assert chunk5_job.duplicate_keys(rows + rows[:1]) == 1
    assert not chunk5_job.arm_health(CFG, "A", rows + rows[:1], EXPECTED)["pass"]
    h = chunk5_job.arm_health(CFG, "A", rows[1:], EXPECTED)
    assert not h["pass"] and "1 missing" in h["coverage_problems"][0]
    h = chunk5_job.arm_health(CFG, "A", rows + [fake_row("A", None, "test", "val_item")], EXPECTED)
    assert not h["pass"] and "1 extra" in h["coverage_problems"][0]
    h = chunk5_job.arm_health(CFG, "B", full_rows("B", CFG["arms"]["B"]["gepa_runs"][:2]), EXPECTED)
    assert not h["pass"]  # one GEPA seed has no rows


def test_arm_f_with_minif2f_rows_fails():
    h = chunk5_job.arm_health(CFG, "F", full_rows("F"), EXPECTED)
    assert not h["pass"] and "unexpected dataset minif2f" in h["coverage_problems"][0]


def test_outage_and_missing_generation_fail_but_missing_verdicts_only_count():
    rows = full_rows("A")
    rows[0].update(judge_missing=True, judge_score=None, ref_missing=True, truth_label=None, truth_source="ref_judge_missing")
    h = chunk5_job.arm_health(CFG, "A", rows, EXPECTED)
    assert h["pass"] and h["counts"]["judge_missing"] == 1 and h["counts"]["truth_missing"] == {"ref_judge_missing": 1}
    rows[1].update(outage=True, compiled=False, compile_status="outage", truth_label=None, truth_source="outage")
    assert not chunk5_job.arm_health(CFG, "A", rows, EXPECTED)["pass"]


def test_health_counts_hold_no_score_fields():
    rows = full_rows("A")
    rows[0].update(format_failure=True, compiled=False, compile_status=None, judge_score=0, truth_label="unfaithful")
    rows[1].update(compiled=False, compile_status="timeout", judge_score=0, truth_label="unfaithful")
    c = chunk5_job.health_counts(rows, 1)
    assert c["format_failure"] == 1 and c["compile_failure_incl_format"] == 2 and c["compile_failure_excl_format"] == 1
    assert c["compile_status_failures"] == {"timeout": 1}
    text = json.dumps(chunk5_job.arm_health(CFG, "A", rows, EXPECTED)).lower()
    assert not any(w in text for w in ("judge_score", "faithful\"", "certified\"", "memoriz", "rate"))


def test_budget_report_flags_one_call_over_the_limit(tmp_path):
    cfg = copy.deepcopy(CFG)
    ids = list(cfg["gepa"]["runs"])
    limit = cfg["gepa"]["max_metric_calls"] + 3 + 70
    for r in ids:
        fake_run(tmp_path / r, calls=limit)
    rep = chunk5_job.budget_report(cfg, tmp_path, ids)
    assert rep["problems"] == [] and rep["runs"][ids[0]]["over_budget_by"] == 73
    (tmp_path / ids[0] / "candidates.json").write_text(json.dumps({"total_metric_calls": limit + 1}))
    assert len(chunk5_job.budget_report(cfg, tmp_path, ids)["problems"]) == 1


def test_log_unmetered_appends_once(tmp_path):
    costs, health = tmp_path / "costs.jsonl", tmp_path / "h.json"
    costs.write_text("")
    health.write_text(json.dumps({"unmetered_pod_time": {"unmetered_hours": 0.5}}))
    row = chunk5_job.log_unmetered(CFG, costs, health)
    assert row["usd"] == 0.5 * CFG["gpu"]["usd_per_hour"] and row["chunk"] == 5
    assert chunk5_job.log_unmetered(CFG, costs, health) is None and len(costs.read_text().splitlines()) == 1


def test_deviation4_counts_and_gepa_missing(tmp_path):
    rows = [fake_row("A", None, "test", "t1", ref_missing=False, judge_missing=False, deviation4={"ref": "reparsed", "opt": "reasked:2"}),
            fake_row("A", None, "test", "t2", ref_missing=True, judge_missing=False, truth_label=None, deviation4={"ref": "still_missing"}),
            fake_row("A", None, "minif2f", "m1")]
    c = chunk5_job.deviation4_counts(rows)
    assert c == {"ref": {"reparsed": 1, "still_missing": 1}, "opt": {"reasked:2": 1}, "ref_missing_after": 1,
                 "opt_missing_after": 0, "truth_missing_after": 1}
    d = tmp_path / "B_s0/candidates"
    d.mkdir(parents=True)
    lines = [{"instructions": "x"}, {"judge_verdict": "faithful", "judge_reason": "ok"},
             {"judge_verdict": "missing", "judge_reason": '{"verdict": "faithful", "reason": "uses {x}"}'},
             {"judge_verdict": "missing", "judge_reason": "no json"}]
    (d / "a.jsonl").write_text("\n".join(json.dumps(x) for x in lines) + "\n")
    assert chunk5_job.gepa_missing_counts(tmp_path, ["B_s0"]) == {"B_s0": {"saved_evaluations": 3, "missing": 2, "parser_would_read": 1}}
