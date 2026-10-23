"""Final evaluation on mocks (runs only against a temporary runs dir with fake DONE markers)."""
import copy

import pytest

from src.axle_check import AxleChecker
from src.config import ROOT, load_config
from src.data.firewall import FirewallError
from src.final_eval import arm_prompts, deviation4, eval_arm, read_rows, write_rows
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


class ScriptedJudge:
    """Stands in for LLMClient.chat: replies per (purpose, sample) from a script, records every call."""

    def __init__(self, replies):
        self.replies, self.calls = replies, []

    def chat(self, model, messages, purpose, max_tokens, sample):
        self.calls.append((purpose, sample, max_tokens))
        return self.replies.get((purpose, sample), "")


def d4_row(**kw):
    row = {"arm": "A", "run_id": None, "dataset": "test", "item_id": "pnv_x", "sample": 0, "normalized": "theorem X : True := by sorry",
           "compiled": True, "certified": False, "judge_verdict": "faithful", "judge_reason": "ok", "judge_score": 1,
           "judge_missing": False, "ref_verdict": "unfaithful", "ref_reason": "r", "ref_error_tag": "Missing premise",
           "ref_missing": False, "truth_label": "unfaithful", "truth_source": "ref_judge", "outage": False,
           "generation_missing": False}
    return {**row, **kw}


D4_ITEMS = {"pnv_x": {"id": "pnv_x", "informal_stmt": "Show True.", "formal_stmt": "theorem t : True := by sorry"}}
REF_MISSING = dict(ref_verdict="missing", ref_reason="", ref_error_tag=None, ref_missing=True, truth_label=None,
                   truth_source="ref_judge_missing")
OPT_MISSING = dict(judge_verdict="missing", judge_reason="", judge_score=None, judge_missing=True)


def test_deviation4_reparses_without_calling():
    from src.scoring.judge import ERROR_TAGS
    stored = '{"verdict": "unfaithful", "reason": "uses {x | x > 0}", "error_tag": "%s"}' % ERROR_TAGS[1]
    rows = [d4_row(**{**REF_MISSING, "ref_reason": stored}), d4_row(**{**OPT_MISSING, "judge_reason": '{"verdict": "faithful", "reason": "a {b}"}'})]
    judge = ScriptedJudge({})
    out = deviation4(CFG, rows, D4_ITEMS, judge)
    assert judge.calls == []
    assert out[0]["ref_verdict"] == "unfaithful" and not out[0]["ref_missing"] and out[0]["truth_source"] == "ref_judge"
    assert out[0]["deviation4"] == {"ref": "reparsed"}
    assert out[1]["judge_score"] == 1 and not out[1]["judge_missing"] and out[1]["deviation4"] == {"opt": "reparsed"}


def test_deviation4_reasks_with_new_samples_and_caps():
    ok = '{"verdict": "faithful", "reason": "same", "error_tag": null}'
    judge = ScriptedJudge({("ref_judge", 3): ok, ("opt_judge", 4): '{"verdict": "unfaithful", "reason": "no"}'})
    rows = [d4_row(**REF_MISSING), d4_row(**OPT_MISSING)]
    out = deviation4(CFG, rows, D4_ITEMS, judge)
    ref_calls = [c for c in judge.calls if c[0] == "ref_judge"]
    opt_calls = [c for c in judge.calls if c[0] == "opt_judge"]
    assert ref_calls == [("ref_judge", 2, 16000), ("ref_judge", 3, 16000)]
    assert opt_calls == [("opt_judge", s, CFG["judges"]["max_tokens"]) for s in (2, 3, 4)]
    assert out[0]["deviation4"] == {"ref": "reasked:2"} and out[0]["truth_label"] == "faithful"
    assert out[1]["deviation4"] == {"opt": "reasked:3"} and out[1]["judge_score"] == 0


def test_deviation4_still_missing_certified_and_untouched_rows():
    judge = ScriptedJudge({})
    still = d4_row(**REF_MISSING)
    cert = d4_row(**{**REF_MISSING, "certified": True, "truth_label": "faithful", "truth_source": "certificate"})
    clean = d4_row()
    out = deviation4(CFG, [still, clean], D4_ITEMS, judge)
    assert len(judge.calls) == 3 and out[0]["ref_missing"] and out[0]["truth_label"] is None
    assert out[0]["deviation4"] == {"ref": "still_missing"} and out[1] == clean and "deviation4" not in out[1]
    judge.replies[("ref_judge", 2)] = '{"verdict": "unfaithful", "reason": "r", "error_tag": "Missing premise"}'
    out = deviation4(CFG, [cert], D4_ITEMS, judge)
    assert out[0]["ref_verdict"] == "unfaithful" and (out[0]["truth_label"], out[0]["truth_source"]) == ("faithful", "certificate")
