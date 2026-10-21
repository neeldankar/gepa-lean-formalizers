import copy
import json

import pytest

from src.config import load_config
from src.llm import BudgetExceeded, LLMClient, spent

CFG = copy.deepcopy(load_config())
MODEL = CFG["judges"]["optimization"]


def fake_post(calls):
    def post(body):
        calls.append(body)
        return {"choices": [{"message": {"content": "hi"}}], "usage": {"prompt_tokens": 1000, "completion_tokens": 1000}}
    return post


def client(tmp_path, calls, cap=None):
    cfg = copy.deepcopy(CFG)
    if cap is not None:
        cfg["budget"]["chunk_caps_usd"][2] = cap
    return LLMClient(cfg, chunk=2, cache_dir=tmp_path / "cache", costs_path=tmp_path / "costs.jsonl", post=fake_post(calls))


def test_cost_logged_and_cache_makes_no_second_call(tmp_path):
    calls = []
    c = client(tmp_path, calls)
    msgs = [{"role": "user", "content": "x"}]
    assert c.chat(MODEL, msgs, purpose="t") == "hi"
    assert c.chat(MODEL, msgs, purpose="t") == "hi"
    assert len(calls) == 1
    row = json.loads((tmp_path / "costs.jsonl").read_text())
    p = CFG["llm"]["prices"][MODEL]
    assert row["usd"] == pytest.approx((1000 * p["input"] + 1000 * p["output"]) / 1e6)


def test_cache_key_includes_sample_and_settings(tmp_path):
    calls = []
    c = client(tmp_path, calls)
    msgs = [{"role": "user", "content": "x"}]
    c.chat(MODEL, msgs, purpose="t")
    c.chat(MODEL, msgs, purpose="t", sample=1)
    c.chat(MODEL, msgs, purpose="t", temperature=0.7)
    assert len(calls) == 3


def test_budget_cap_stops_calls(tmp_path):
    calls = []
    c = client(tmp_path, calls, cap=0.0001)
    c.chat(MODEL, [{"role": "user", "content": "a"}], purpose="t")  # spends more than the cap
    with pytest.raises(BudgetExceeded):
        c.chat(MODEL, [{"role": "user", "content": "b"}], purpose="t")
    assert len(calls) == 1 and spent(2, tmp_path / "costs.jsonl") > 0.0001


def test_client_timeout_allows_long_reflections():
    # A non-streaming call sends nothing until it is done: Kimi-K3 reflections took 260 s to over 300 s in the
    # chunk 4 preflight, so a 300 s timeout retried (and may have re-billed) them.
    from src.config import load_config
    assert load_config()["llm"]["timeout_seconds"] >= 1200
