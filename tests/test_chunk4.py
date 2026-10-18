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


def fake_pilot_rows(n_items=30, a2_compiled=6):
    rows = []
    for k, name in enumerate(chunk4.ALL_CONFIGS):
        for i in range(n_items):
            compiled = i < a2_compiled if name == "qwen_a2" else (i + k) % 3 != 0
            rows.append({"config": name, "item_id": f"pnv_{i:03d}", "compiled": compiled,
                         "ref_verdict": "faithful" if i % 2 else "unfaithful", "normalized": f"theorem X : {i} = {i} := by sorry"})
    return rows


def test_label_sample_quota_distinct_compiled_and_blind():
    # Only 6 rerun outputs compile: 4 more Qwen3-8B outputs come from the first thinking-off run.
    picked = chunk4.pick_label_rows(fake_pilot_rows(), CFG)
    assert len(picked) == 20 and len({r["item_id"] for r in picked}) == 20 and all(r["compiled"] for r in picked)
    by = {c: sum(r["config"] == c for r in picked) for c in chunk4.ALL_CONFIGS}
    assert by == {"qwen_a2": 6, "qwen_nothink": 4, "qwen_think": 0, "reform": 10}
    full = chunk4.pick_label_rows(fake_pilot_rows(a2_compiled=30), CFG)
    assert sum(r["config"] == "qwen_a2" for r in full) == 10 and sum(r["config"] == "reform" for r in full) == 10
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
