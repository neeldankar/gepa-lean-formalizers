"""Final evaluation on mocks (runs only against a temporary runs dir with fake DONE markers)."""
import copy

import pytest

from src.axle_check import AxleChecker
from src.config import ROOT, load_config
from src.data.firewall import FirewallError
from src.final_eval import arm_prompts, eval_arm, read_rows, write_rows
from src.llm import LLMClient
from src.mocks import MockAxleClient, MockPosts

CFG = copy.deepcopy(load_config())
CFG["axle"]["outage_backoff_seconds"] = 0


def fake_runs(tmp_path):
    runs = tmp_path / "runs"
    for run_id in CFG["gepa"]["runs"]:
        (runs / run_id).mkdir(parents=True)
        (runs / run_id / "DONE").write_text("ok\n")
        (runs / run_id / "best_prompt.txt").write_text(f"prompt of {run_id}. Keep every hypothesis from the problem.\n")
    return runs


def clients(tmp_path, posts):
    kw = dict(cache_dir=tmp_path / "llm", costs_path=tmp_path / "costs.jsonl")
    gen = LLMClient(CFG, 5, post=posts.formalizer, base_url="http://mock", api_key_env=None, **kw)
    judge = LLMClient(CFG, 5, post=posts.judge, **kw)
    return gen, judge, AxleChecker(CFG["axle"], client_factory=MockAxleClient, cache_dir=tmp_path / "axle")


def test_locked_without_done_markers(tmp_path):
    gen, judge, checker = clients(tmp_path, MockPosts())
    with pytest.raises(FirewallError):
        eval_arm(CFG, "A", gen, judge, checker, tmp_path / "empty_runs", ROOT)


def test_arm_prompts_for_gepa_arm(tmp_path):
    prompts = arm_prompts(CFG, "B", fake_runs(tmp_path))
    assert [(r, s) for r, s, _ in prompts] == [("B_s0", 0), ("B_s1", 1), ("B_s2", 2)]
    assert prompts[1][2].startswith("prompt of B_s1")


def test_arm_a_and_f_rows(tmp_path):
    runs = fake_runs(tmp_path)
    gen, judge, checker = clients(tmp_path, MockPosts())
    rows_a = eval_arm(CFG, "A", gen, judge, checker, runs, ROOT)
    assert {r["dataset"] for r in rows_a} == {"test", "minif2f"}
    assert sum(r["dataset"] == "test" for r in rows_a) == 247 and sum(r["dataset"] == "minif2f" for r in rows_a) == 243
    assert all(r["judge_score"] in (0, 1) and r["truth_label"] in ("faithful", "unfaithful") for r in rows_a)
    assert not any(r["judge_score"] and not r["compiled"] for r in rows_a)
    rows_f = eval_arm(CFG, "F", gen, judge, checker, runs, ROOT)
    assert {r["dataset"] for r in rows_f} == {"test"} and len(rows_f) == 247
    write_rows(tmp_path / "A.jsonl.gz", rows_a)
    assert read_rows(tmp_path / "A.jsonl.gz") == rows_a
