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
    llm = load_config()["llm"]
    assert llm["long_timeout_seconds"] >= 1200 and {"reflection", "generate"} <= set(llm["long_purposes"])



def hanging_client(tmp_path, post, timeout=0.3, retries=1):
    import copy
    from src.config import load_config
    from src.llm import LLMClient
    cfg = copy.deepcopy(load_config())
    cfg["llm"].update(timeout_seconds=timeout, long_timeout_seconds=timeout, retries=retries, long_retries=retries, backoff_seconds=0,
                      purpose_limits={})
    cfg["llm"]["prices"]["m"] = {"input": 0, "output": 0}
    return LLMClient(cfg, 4, cache_dir=tmp_path / "c", costs_path=tmp_path / "costs.jsonl", post=post)


def test_a_hung_call_is_cut_off_retried_then_fails_loudly(tmp_path):
    import time
    import pytest
    from src.llm import LLMError
    calls = []
    def hang(body):
        calls.append(time.monotonic())
        time.sleep(30)  # a server that never answers
    client = hanging_client(tmp_path, hang)
    t0 = time.monotonic()
    for purpose in ("opt_judge", "ref_judge", "reflection", "generate"):
        calls.clear()
        with pytest.raises(LLMError, match="gave up after 2 attempts"):
            client.chat("m", [{"role": "user", "content": purpose}], purpose=purpose)
        assert len(calls) == 2  # one retry, then the failure is raised, never skipped
    assert time.monotonic() - t0 < 5
    assert not (tmp_path / "costs.jsonl").exists()  # nothing was billed or cached as a reply


def test_non_retryable_error_is_not_retried(tmp_path):
    import pytest
    from src.llm import LLMError
    calls = []
    def bad(body):
        calls.append(1)
        raise LLMError("HTTP 400: endpoint_not_ready")
    with pytest.raises(LLMError, match="400"):
        hanging_client(tmp_path, bad, retries=3).chat("m", [{"role": "user", "content": "x"}], purpose="reflection")
    assert len(calls) == 1


def test_reflection_has_its_own_cap_and_every_failed_attempt_is_logged(tmp_path):
    import json
    import time
    import pytest
    from src.llm import LLMError
    client = hanging_client(tmp_path, lambda body: time.sleep(30), timeout=5, retries=3)
    client.purpose_limits = {"reflection": {"timeout_seconds": 0.2, "retries": 1}}
    assert client.limits("reflection") == (0.2, 1) and client.limits("ref_judge") == (5, 3)
    with pytest.raises(LLMError):
        client.chat("m", [{"role": "user", "content": "r"}], purpose="reflection")
    rows = [json.loads(l) for l in (tmp_path / "api_failures.jsonl").read_text().splitlines()]
    assert [r["kind"] for r in rows] == ["timeout", "timeout"] and all(r["purpose"] == "reflection" for r in rows)


def test_cost_rows_carry_latency(tmp_path):
    import json
    reply = {"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 1, "completion_tokens": 1}}
    client = hanging_client(tmp_path, lambda body: reply)
    client.chat("m", [{"role": "user", "content": "x"}], purpose="opt_judge")
    row = json.loads((tmp_path / "costs.jsonl").read_text())
    assert "seconds" in row and row["seconds"] >= 0


REPLY = {"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 1, "completion_tokens": 1}}


def retry_client(tmp_path, post):
    """The real config's limits (reflection: 4 retries, 30 s base backoff), with sleeps recorded, not slept."""
    cfg = copy.deepcopy(CFG)
    cfg["llm"]["prices"]["m"] = {"input": 0, "output": 0}
    c = LLMClient(cfg, 4, cache_dir=tmp_path / "c", costs_path=tmp_path / "costs.jsonl", post=post)
    c.slept = []
    c.sleep = c.slept.append
    return c


def test_reflection_retries_four_times_with_exponential_backoff_and_jitter(tmp_path):
    # Chunk 5 deviation (Neel, 2026-10-22): reflection retries 1 to 4, about 30, 60, 120, 240 s apart.
    from src.llm import RetryableError
    calls = []
    def flaky(body):
        calls.append(1)
        if len(calls) < 5:
            raise RetryableError("HTTP 503: Service unavailable")
        return REPLY
    c = retry_client(tmp_path, flaky)
    assert c.limits("reflection") == (600, 4)
    assert c.chat("m", [{"role": "user", "content": "r"}], purpose="reflection") == "ok"
    assert len(calls) == 5 and len(c.slept) == 4
    for wait, base in zip(c.slept, (30, 60, 120, 240)):
        assert 0.8 * base <= wait <= 1.2 * base
    rows = [json.loads(l) for l in (tmp_path / "api_failures.jsonl").read_text().splitlines()]
    assert len(rows) == 4 and all(r["purpose"] == "reflection" for r in rows)


def test_reflection_gives_up_after_five_attempts(tmp_path):
    from src.llm import LLMError, RetryableError
    calls = []
    def down(body):
        calls.append(1)
        raise RetryableError("HTTP 429: too many requests")
    c = retry_client(tmp_path, down)
    with pytest.raises(LLMError, match="gave up after 5 attempts"):
        c.chat("m", [{"role": "user", "content": "r"}], purpose="reflection")
    assert len(calls) == 5 and len(c.slept) == 4


def test_jitter_varies_the_waits(tmp_path):
    c = retry_client(tmp_path, None)
    assert len({round(c.retry_delay(0, "reflection", None), 6) for _ in range(20)}) > 1


def test_retry_after_is_honored_when_longer_and_capped(tmp_path):
    from src.llm import MAX_RETRY_AFTER, RetryableError
    c = retry_client(tmp_path, None)
    assert c.retry_delay(0, "reflection", RetryableError("429", retry_after=200)) == 200
    assert 24 <= c.retry_delay(0, "reflection", RetryableError("429", retry_after=5)) <= 36  # backoff still applies
    assert c.retry_delay(0, "reflection", RetryableError("429", retry_after=5000)) == MAX_RETRY_AFTER
    calls = []
    def limited(body):
        calls.append(1)
        if len(calls) == 1:
            raise RetryableError("HTTP 429: too many requests", retry_after=90)
        return REPLY
    c = retry_client(tmp_path, limited)
    c.chat("m", [{"role": "user", "content": "r"}], purpose="reflection")
    assert c.slept == [90]


def test_post_reads_retry_after_from_a_429(tmp_path, monkeypatch):
    import email.message
    import io
    import urllib.error
    import src.llm as llm
    from src.llm import RetryableError
    def fail_with(code, after):
        headers = email.message.Message()
        if after is not None:
            headers["Retry-After"] = after
        err = urllib.error.HTTPError("u", code, "x", headers, io.BytesIO(b"{}"))
        def urlopen(*a, **k):
            raise err
        monkeypatch.setattr(llm.urllib.request, "urlopen", urlopen)
    monkeypatch.setenv("TOGETHER_API_KEY", "test")
    c = retry_client(tmp_path, None)
    for code, after, want in ((429, "45", 45.0), (429, None, None), (429, "soon", None), (503, "45", None)):
        fail_with(code, after)
        with pytest.raises(RetryableError) as e:
            c._post({"model": "m"})
        assert e.value.retry_after == want


def test_retry_after_http_date():
    from datetime import datetime, timezone
    from src.llm import retry_after_seconds
    now = datetime(2026, 10, 22, 7, 27, 0, tzinfo=timezone.utc)
    assert retry_after_seconds("Thu, 22 Oct 2026 07:28:00 GMT", now=now) == 60
    assert retry_after_seconds("Thu, 22 Oct 2026 07:00:00 GMT", now=now) == 0
    assert retry_after_seconds("", now=now) is None
