"""Chunk 4 pilot helpers: item choice, label sample, agreement, go checks, projection, GPU cost, runner overrides."""
import copy
import json
from datetime import datetime, timedelta, timezone

import pytest

from scripts import chunk4
from src import runner
from src.axle_check import AxleChecker
from src.config import ROOT, load_config
from src.data.firewall import gepa_items
from src.llm import LLMClient
from src.mocks import MockAxleClient, MockPosts

CFG = load_config()


def test_pilot_items_are_val_only_and_seeded():
    items = chunk4.pilot_items(CFG)
    splits = json.loads((ROOT / "data/splits.json").read_text())
    assert len(items) == 30 and {it["id"] for it in items} <= set(splits["val"])
    assert [it["id"] for it in items] == [it["id"] for it in chunk4.pilot_items(CFG)]


def fake_pilot_rows(n_items=30, latest_compiled=6):
    rows = []
    for k, name in enumerate(chunk4.ALL_CONFIGS):
        for i in range(n_items):
            compiled = i < latest_compiled if name == "qwen_a3" else (i + k) % 3 != 0
            rows.append({"config": name, "item_id": f"pnv_{i:03d}", "compiled": compiled,
                         "ref_verdict": "faithful" if i % 2 else "unfaithful", "normalized": f"theorem X : {i} = {i} := by sorry"})
    return rows


def test_label_sample_quota_distinct_compiled_and_blind():
    # Only 6 outputs of the latest rerun compile: 4 more Qwen3-8B outputs come from the previous rerun.
    picked = chunk4.pick_label_rows(fake_pilot_rows(), CFG)
    assert len(picked) == 20 and len({r["item_id"] for r in picked}) == 20 and all(r["compiled"] for r in picked)
    by = {c: sum(r["config"] == c for r in picked) for c in chunk4.ALL_CONFIGS}
    assert by == {"qwen_a3": 6, "qwen_a2": 4, "qwen_nothink": 0, "qwen_think": 0, "reform": 10}
    full = chunk4.pick_label_rows(fake_pilot_rows(latest_compiled=30), CFG)
    assert sum(r["config"] == "qwen_a3" for r in full) == 10 and sum(r["config"] == "reform" for r in full) == 10
    val = gepa_items("val")
    items = {f"pnv_{i:03d}": val[i] for i in range(30)}
    mapping, records = chunk4.label_records(picked, items)
    assert all(set(r) == {"label_id", "english", "reference", "candidate"} for r in records)
    assert [m["label_id"] for m in mapping] == [r["label_id"] for r in records]


def test_agreement_counts_unsure_as_disagreeing():
    rows = [{"config": "reform", "item_id": f"i{k}", "ref_verdict": v, "truth_label": t, "judge_verdict": j, "certified": False}
            for k, (v, t, j) in enumerate([("faithful", "faithful", "faithful"), ("unfaithful", "faithful", "faithful"),
                                           ("unfaithful", "unfaithful", "faithful"), ("faithful", "faithful", "faithful")])]
    mapping = [{"label_id": f"P{k}", "config": "reform", "item_id": f"i{k}"} for k in range(4)]
    labels = {"P0": "faithful", "P1": "unfaithful", "P2": "unfaithful", "P3": "unsure"}
    out, per = chunk4.agreement(rows, mapping, labels)
    assert out["ref_judge"] == {"agree": 3, "of": 4} and out["truth_label"] == {"agree": 2, "of": 4}
    assert out["opt_judge"] == {"agree": 1, "of": 4} and out["unsure"] == 1 and out["n_decided"] == 3
    assert per[1]["label"] == "unfaithful" and per[1]["ref_judge"] == "unfaithful"


@pytest.mark.parametrize("rate,agree,em,total,expected", [
    (35.0, 17, {"a": 5.0, "b": 19.9}, 250.0, [True, True, True, True]),
    (9.9, 16, {"a": 0.0}, 299.9, [False, True, True, True]),
    (70.0, 15, {"a": 20.0}, 300.0, [True, False, False, False]),
])
def test_go_checks(rate, agree, em, total, expected):
    assert [c["go"] for c in chunk4.go_checks(rate, agree, em, total)] == expected


def test_projection_arithmetic():
    cfg = copy.deepcopy(CFG)
    cfg["gpu"]["usd_per_hour"] = 4.0
    cfg["gepa"]["max_metric_calls"] = 800
    m = {"minif2f_items": 243, "gen_s_per_item": {"qwen": 3.6, "reform": 7.2}, "api_per_output": {"qwen": 0.001, "reform": 0.002},
         "gepa_gpu_s_per_call": 9.0, "gepa_api_per_call": 0.01, "armf_usd_per_item": 0.02, "gloss_usd": 0.001,
         "setup_hours": 0.5, "spent_usd": 20.0}
    p = chunk4.projection(m, cfg)
    qwen_h = 800 * 9.0 / 3600                                   # 2 h per Qwen run, 4 h per ReForm run
    assert p["gepa_gpu_usd_serial"] == pytest.approx(3 * (qwen_h + 2 * qwen_h) * 4.0)
    assert p["gepa_gpu_usd_parallel"] == pytest.approx(2 * qwen_h * 4.0)
    assert p["gepa_api_usd"] == pytest.approx(6 * 800 * 0.01)
    eval_h = 490 * (5 * 3.6 + 4 * 7.2) / 3600
    assert p["final_eval_gpu_hours"] == pytest.approx(eval_h)
    assert p["final_eval_api_usd"] == pytest.approx(490 * (5 * 0.001 + 4 * 0.002))
    assert p["arm_f_usd"] == pytest.approx(247 * 0.021)
    chunk5 = 72 + 48 + (eval_h + 0.5) * 4 + 490 * 0.013 + 247 * 0.021
    assert p["chunk5_usd_serial"] == pytest.approx(chunk5)
    assert p["total_usd_upper"] == pytest.approx(20 + chunk5 + 10)


def test_gpu_balance_tops_up_to_wall_clock(tmp_path):
    costs = tmp_path / "costs.jsonl"
    start = datetime(2026, 10, 18, 18, 0, tzinfo=timezone.utc)
    t = (start + timedelta(minutes=30)).isoformat()
    costs.write_text(json.dumps({"time": t, "chunk": 4, "purpose": "gpu", "usd": 1.0, "hours": 0.25}) + "\n"
                     + json.dumps({"time": t, "chunk": 3, "purpose": "gpu", "usd": 9.0, "hours": 5.0}) + "\n")
    cfg = copy.deepcopy(CFG)
    cfg["gpu"]["usd_per_hour"] = 4.0
    out = chunk4.gpu_balance(cfg, start, start + timedelta(hours=2), costs_path=costs)
    assert out["added_hours"] == pytest.approx(1.75) and out["total_usd"] == pytest.approx(8.0)
    again = chunk4.gpu_balance(cfg, start, start + timedelta(hours=2), costs_path=costs)
    assert again["added_hours"] == 0  # idempotent: a second call at the same time adds nothing


def test_runner_honors_pilot_budget_and_thinking_override(tmp_path):
    cfg = copy.deepcopy(CFG)
    cfg["gepa"]["max_metric_calls"] = 800
    cfg["gepa"]["runs"] = {"pilot_qwen": {**CFG["pilot"]["gepa_run"], "max_metric_calls": 60, "enable_thinking": True}}
    cfg["axle"]["outage_backoff_seconds"] = 0
    posts, seen = MockPosts(), []
    def formalizer(body):
        seen.append(body.get("chat_template_kwargs"))
        return posts.formalizer(body)
    kw = dict(cache_dir=tmp_path / "llm", costs_path=tmp_path / "costs.jsonl")
    gen = LLMClient(cfg, 4, post=formalizer, base_url="http://mock", api_key_env=None, **kw)
    judge = LLMClient(cfg, 4, post=posts.judge, **kw)
    refl = LLMClient(cfg, 4, post=posts.reflection, **kw)
    checker = AxleChecker(cfg["axle"], client_factory=MockAxleClient, cache_dir=tmp_path / "axle")
    result = runner.run_gepa(cfg, "pilot_qwen", gen, judge, refl, checker, runs_dir=tmp_path / "runs")
    assert result["status"] == "done" and 60 <= result["total_metric_calls"] < 120
    assert seen and all(k == {"enable_thinking": True} for k in seen)
    assert cfg["models"]["qwen3-8b"]["enable_thinking"] == CFG["models"]["qwen3-8b"]["enable_thinking"]  # not mutated


def test_gpu_balance_counts_each_pod_session_separately(tmp_path):
    costs = tmp_path / "costs.jsonl"
    cfg = copy.deepcopy(CFG)
    cfg["gpu"]["usd_per_hour"] = 4.0
    s1 = datetime(2026, 10, 18, 18, 0, tzinfo=timezone.utc)
    chunk4.gpu_balance(cfg, s1, s1 + timedelta(hours=1), costs_path=costs)  # session 1: 1 h
    s2 = s1 + timedelta(hours=3)                                            # pod stopped, then restarted
    out = chunk4.gpu_balance(cfg, s2, s2 + timedelta(minutes=30), costs_path=costs)
    assert out["logged_hours_before"] == 0 and out["added_hours"] == pytest.approx(0.5)
    rows = [json.loads(line) for line in costs.read_text().splitlines()]
    assert sum(r["hours"] for r in rows) == pytest.approx(1.5)


@pytest.mark.live
def test_fewshot_pool_and_block_match_the_saved_file():
    from src.axle_check import AxleChecker
    pool = chunk4.fewshot_pool(AxleChecker(CFG["axle"]), gepa_items("train"))
    ids = {it["id"] for it in pool}
    train = json.loads((ROOT / "data/splits.json").read_text())["train"]
    assert ids <= set(train) and "pnv_280" not in ids and all(not it["helper"].strip() for it in pool)
    f = CFG["fewshot"]
    import random
    examples = random.Random(f["seed"]).sample(pool, f["n"])
    assert (ROOT / f["path"]).read_text() == chunk4.fewshot_block(examples) + "\n"
    assert [it["id"] for it in examples] == f["ids"] == ["pnv_218", "pnv_226", "pnv_018"]  # never redrawn
    assert "open Fintype" in chunk4.fewshot_block(examples).split("Example 3:")[1]           # @card's open line is shown
    assert all(chunk4.sorry_ending(it["formal_stmt"]).endswith(" := by sorry") for it in examples)


@pytest.mark.parametrize("check,ok", [
    ({"kind": "reflection", "new_cost_rows": 1, "finish_reason": "stop", "seed": "S", "new_instruction": "New rules.", "failures": []}, True),
    ({"kind": "reflection", "new_cost_rows": 1, "finish_reason": "length", "seed": "S", "new_instruction": "New rules.", "failures": []}, False),
    ({"kind": "reflection", "new_cost_rows": 1, "finish_reason": "stop", "seed": "S", "new_instruction": "S", "failures": []}, False),
    ({"kind": "reflection", "new_cost_rows": 1, "finish_reason": "stop", "seed": "S", "new_instruction": "", "failures": []}, False),
    ({"kind": "reflection", "new_cost_rows": 0, "finish_reason": "stop", "seed": "S", "new_instruction": "New.", "failures": ["HTTP 400"]}, False),
    ({"kind": "reflection", "new_cost_rows": 0, "finish_reason": "stop", "seed": "S", "new_instruction": "New.", "failures": []}, False),  # cached
    ({"kind": "arm_f", "new_cost_rows": 1, "finish_reason": "stop", "format_failure": False}, True),
    ({"kind": "arm_f", "new_cost_rows": 1, "finish_reason": "stop", "format_failure": True}, False),
    ({"kind": "judge", "new_cost_rows": 1, "verdict": "unfaithful"}, True),
    ({"kind": "judge", "new_cost_rows": 2, "verdict": "unparseable"}, False),
])
def test_preflight_verdict(check, ok):
    assert chunk4.preflight_verdict(check)["pass"] is ok


def test_fresh_preflight_cache_dir_is_new(tmp_path):
    a = chunk4.fresh_cache_dir(tmp_path)
    assert not a.exists() and a.parent == tmp_path


def test_gepa_refuses_a_finished_run_dir(tmp_path):
    chunk4.refuse_finished_run(tmp_path / "pilot_qwen")  # nothing there: fine
    (tmp_path / "pilot_qwen").mkdir()
    (tmp_path / "pilot_qwen/DONE").write_text("ok\n")
    with pytest.raises(SystemExit):
        chunk4.refuse_finished_run(tmp_path / "pilot_qwen")


def test_preflight_gate():
    from datetime import datetime, timezone
    now = datetime(2026, 10, 22, 2, 0, tzinfo=timezone.utc)
    passing = {"time": "2026-10-21T21:40:00+00:00", "checks": [{"name": n, "pass": True, "reasons": []} for n in chunk4.PREFLIGHT_CHECKS]}
    assert chunk4.preflight_gate(passing, now) == (True, [])
    # Neel, 2026-10-22: the 15-record reflection and arm F are reported but do not gate the pilot
    not_gating = {**passing, "checks": [{**c, "pass": c["name"] not in ("reflection_long_15", "arm_f_generate"), "reasons": ["x"]}
                                        for c in passing["checks"]]}
    assert chunk4.preflight_gate(not_gating, now) == (True, [])
    for name in chunk4.GATE_CHECKS:
        one_failed = {**passing, "checks": [{**c, "pass": c["name"] != name, "reasons": ["finish_reason length"]} for c in passing["checks"]]}
        assert not chunk4.preflight_gate(one_failed, now)[0]
        missing = {**passing, "checks": [c for c in passing["checks"] if c["name"] != name]}
        assert not chunk4.preflight_gate(missing, now)[0]
    assert set(chunk4.GATE_CHECKS) == set(chunk4.PREFLIGHT_CHECKS) - {"reflection_long_15", "arm_f_generate"}
    stale = {**passing, "time": "2026-10-20T21:40:00+00:00"}
    ok, reasons = chunk4.preflight_gate(stale, now)
    assert not ok and "old" in reasons[0]


def test_reliability_and_overnight_projection():
    costs = [{"run_id": "pilot_qwen", "purpose": "reflection", "seconds": s} for s in (100, 300, 150, 900)]
    costs += [{"run_id": "pilot_qwen", "purpose": "opt_judge", "seconds": 2}, {"run_id": "other", "purpose": "reflection", "seconds": 5000}]
    fails = [{"run_id": "pilot_qwen", "purpose": "reflection", "kind": "timeout"}, {"run_id": "pilot_qwen", "purpose": "ref_judge", "kind": "RetryableError"}]
    rel = chunk4.reliability(costs, fails, "pilot_qwen")
    assert (rel["reflection_calls"], rel["reflection_median_s"], rel["reflection_slowest_s"]) == (4, 300, 900)
    assert rel["failed_attempts"] == 2 and rel["timed_out"] == 1 and rel["reflection_hang_rate"] == pytest.approx(1 / 5)
    cfg = copy.deepcopy(CFG)
    cfg["gepa"]["max_metric_calls"] = 800
    cfg["llm"]["purpose_limits"] = {"reflection": {"timeout_seconds": 600, "retries": 1}}
    m = {"gen_s_per_item": {"qwen": 1.0, "reform": 4.0}, "eval_wall_s_per_call": 9.0, "reflections_per_run": 20,
         "reflection_median_s": 180, "final_eval_hours": 2.0, "setup_hours": 0.25}
    o = chunk4.overnight_hours(m, rel, cfg)
    gepa = (800 * 9 * 4 + 20 * 180) / 3600                                   # ReForm-8B sets the pace; reflection time not scaled
    assert o["gepa_parallel_h"] == pytest.approx(gepa)
    assert o["reflection_calls_per_run"] == 20
    assert o["expected_hang_stall_h"] == pytest.approx(0.2 * 20 * 600 / 3600)  # 4 hangs x 10 min
    assert o["total_h"] == pytest.approx(gepa + 0.2 * 20 * 600 / 3600 + 2 + 0.25)


def test_reflections_per_run_matches_the_pilot():
    # the pilot: 158 metric calls, 3 reflections, 1 accepted: 70 + 3 x 6 + 70
    assert chunk4.reflections_per_run(158, 70, 3, 1 / 3) == pytest.approx(3)
    assert chunk4.reflections_per_run(800, 70, 3, 0.0) == pytest.approx(730 / 6)
    assert chunk4.reflections_per_run(800, 70, 3, 1.0) == pytest.approx(730 / 76)


def test_projection_reflection_terms():
    cfg = copy.deepcopy(CFG)
    cfg["gpu"]["usd_per_hour"] = 4.0
    cfg["gepa"]["max_metric_calls"] = 800
    m = {"minif2f_items": 243, "gen_s_per_item": {"qwen": 3.6, "reform": 7.2}, "api_per_output": {"qwen": 0.001, "reform": 0.002},
         "gepa_gpu_s_per_call": 9.0, "gepa_api_per_call": 0.01, "armf_usd_per_item": 0.02, "gloss_usd": 0.001,
         "setup_hours": 0.5, "spent_usd": 20.0, "reflections_per_run": 25, "reflection_median_s": 144, "reflection_usd": 0.1}
    p = chunk4.projection(m, cfg)
    assert p["gepa_api_usd"] == pytest.approx(6 * (800 * 0.01 + 25 * 0.1))
    refl_h = 25 * 144 / 3600
    assert p["gepa_gpu_usd_parallel"] == pytest.approx((800 * 9 * 2 / 3600 + refl_h) * 4.0)


def test_preflight_api_error_is_a_failed_check():
    check = {"kind": "arm_f", "new_cost_rows": 0, "error": "LLMError: gave up after 1 attempts: HTTP 503: Service unavailable"}
    v = chunk4.preflight_verdict(check)
    assert not v["pass"] and "503" in v["reasons"][0]
    judge = {"kind": "judge", "new_cost_rows": 0, "verdict": "error"}
    assert not chunk4.preflight_verdict(judge)["pass"]


def test_preflight_limits_cap_and_once():
    cfg = copy.deepcopy(load_config())
    chunk4.preflight_limits(cfg, ["--fresh", "--cap", "600"])
    client = LLMClient(cfg, 4, run_id="preflight")
    for purpose in ("reflection", "generate", "judge"):
        assert client.limits(purpose)[0] <= 600
    assert client.limits("reflection")[1] == load_config()["llm"]["purpose_limits"]["reflection"]["retries"]
    assert load_config()["llm"]["long_timeout_seconds"] == 1800  # config.yaml itself is untouched
    chunk4.preflight_limits(cfg, ["--once"])
    client = LLMClient(cfg, 4, run_id="preflight")
    assert all(client.limits(p)[1] == 0 for p in ("reflection", "generate", "judge"))


def test_reflection_load_runs_concurrently_and_counts_failures(tmp_path):
    import threading
    posts, barrier = MockPosts(), threading.Barrier(6, timeout=10)
    def post(body):
        barrier.wait()  # passes only if all 6 calls are in flight at once
        if "seed 5" in body["messages"][0]["content"]:
            raise ValueError("bad request")  # not retryable: a failed call
        return posts.reflection(body)
    costs = tmp_path / "costs.jsonl"
    client = LLMClient(CFG, 4, post=post, cache_dir=tmp_path / "llm", costs_path=costs)
    seeds = [f"seed {i}" for i in range(6)]
    prompts = [f"Instruction:\n```\n{s}\n```\nexamples" for s in seeds]
    out = chunk4.reflection_load(client, "moonshotai/Kimi-K3", 32000, prompts, seeds, costs_path=costs)
    assert out["concurrent"] == 6 and out["passed"] == 5 and out["new_cost_rows"] == 5
    bad = out["calls"][5]
    assert not bad["pass"] and "bad request" in bad["error"]
    assert all(c["pass"] and c["new_instruction"] != c["seed"] for c in out["calls"][:5])
    assert out["usd"] == pytest.approx(sum(r["usd"] for r in map(json.loads, open(costs))))


def test_armf_rows_use_fewshot_and_compile(tmp_path):
    posts, prompts = MockPosts(), []
    def post(body):
        prompts.append(body["messages"][0]["content"])
        return posts.formalizer(body)
    kw = dict(cache_dir=tmp_path / "llm", costs_path=tmp_path / "costs.jsonl")
    genc = LLMClient(CFG, 4, post=post, base_url="http://mock", api_key_env=None, **kw)
    checker = AxleChecker(CFG["axle"], client_factory=MockAxleClient, cache_dir=tmp_path / "axle")
    items = [it for it in gepa_items("train") if it["id"] in ("pnv_004", "pnv_011")]
    rows = chunk4.armf_rows(genc, CFG, checker, items)
    assert [r["item_id"] for r in rows] == ["pnv_004", "pnv_011"]
    fewshot = chunk4.load_fewshot(CFG["arms"]["F"]["fewshot"])
    assert fewshot and all(fewshot.strip()[:200] in p for p in prompts)
    assert all(r["finish_reason"] == "stop" and r["completion_tokens"] == 50 and not r["format_failure"] for r in rows)
    assert all(isinstance(r["compiled"], bool) for r in rows)
