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
    assert [(r, s) for r, s, _, _ in prompts] == [("B_s0", 0), ("B_s1", 1), ("B_s2", 2)]
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


def test_fewshot_goes_to_a_b_e_f_only(tmp_path):
    runs = fake_runs(tmp_path)
    shots = (ROOT / "prompts/fewshot.txt").read_text().rstrip("\n")
    for arm in ("A", "B", "E", "F", "C", "D"):
        prompts = arm_prompts(CFG, arm, runs)
        want = shots if arm in ("A", "B", "E", "F") else ""
        assert all(p[3] == want for p in prompts), arm
        assert all("Example 1:" not in p[2] for p in prompts), arm  # the block is never in the instructions


def test_missing_judge_verdicts_are_kept_not_outages(tmp_path):
    from src.data.firewall import gepa_items
    from src.final_eval import score_row
    posts = MockPosts()
    garbage = lambda body: posts._reply("no JSON here")  # both judges, both attempts
    kw = dict(cache_dir=tmp_path / "llm", costs_path=tmp_path / "costs.jsonl")
    gen = LLMClient(CFG, 5, post=posts.formalizer, base_url="http://mock", api_key_env=None, **kw)
    judge = LLMClient(CFG, 5, post=garbage, **kw)
    checker = AxleChecker(CFG["axle"], client_factory=MockAxleClient, cache_dir=tmp_path / "axle")
    item = next(it for it in gepa_items("train") if it["id"] == "pnv_004")
    r = score_row(CFG, "A", "qwen3-8b", None, None, "dryrun_test", "Translate.", item, 0, gen, judge, checker)
    assert r["compiled"] and not r["outage"]
    assert r["judge_missing"] and r["judge_score"] is None and r["judge_verdict"] == "missing"
    assert r["ref_missing"] and r["ref_verdict"] == "missing"
    assert r["truth_label"] in (None, "faithful")  # None unless a certificate settled it


def test_arm_f_call_out_of_retries_is_a_missing_row_not_an_error(monkeypatch):
    # Deviation 3: recorded as missing for that item; never a format failure or a job-ending error.
    import pytest
    from src.llm import LLMError
    def down(*a, **k):
        raise LLMError("gave up after 5 attempts: HTTP 503")
    from src import final_eval
    monkeypatch.setattr(final_eval, "generate", down)
    item = {"id": "pnv_x", "informal_stmt": "x", "formal_stmt": "theorem x : True := by sorry"}
    row = final_eval.score_row(CFG, "F", "arm_f", None, None, "test", "instructions", item, 0, None, None, None)
    assert row["generation_missing"] and "gave up after 5 attempts" in row["generation_error"]
    assert row["format_failure"] is None and row["compiled"] is None and row["truth_label"] is None
    assert row["judge_score"] is None and not row["outage"] and row["truth_source"] == "generation_missing"
    assert set(row) >= {"arm", "item_id", "dataset", "sample", "gepa_seed", "memorized"}
    with pytest.raises(LLMError):  # any other arm still fails loudly
        final_eval.score_row(CFG, "C", "reform-8b", None, None, "test", "instructions", item, 0, None, None, None)
