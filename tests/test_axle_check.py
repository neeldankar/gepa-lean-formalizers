import os
from types import SimpleNamespace

import axle
import pytest

from src.axle_check import LEAN_ERROR, OK, OUTAGE, RESOURCE, TIMEOUT, AxleChecker
from src.config import load_config, load_env

CFG = {**load_config()["axle"], "outage_backoff_seconds": 0}

GOOD = "import Mathlib\n\ntheorem t (n : ℕ) (h : 0 < n) : 1 ≤ n := by\n  omega"
SORRY = "import Mathlib\n\ntheorem t (n : ℕ) : n + 0 = n := by\n  sorry"
BROKEN = "import Mathlib\n\ntheorem t (n : ℕ) : n + 0 = not_a_lemma n := by\n  sorry"


class FakeClient:
    """Stands in for axle.AxleClient: returns or raises the next scripted outcome."""

    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        pass

    async def check(self, **kwargs):
        self.calls += 1
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def ok_response(okay=True, errors=(), failed=()):
    return SimpleNamespace(okay=okay, lean_messages=SimpleNamespace(errors=list(errors)), failed_declarations=list(failed))


def checker_with(tmp_path, outcomes):
    client = FakeClient(outcomes)
    return AxleChecker(CFG, client_factory=lambda: client, cache_dir=tmp_path), client


def test_outage_is_retried_then_reported_and_not_cached(tmp_path):
    outages = [axle.AxleIsUnavailable("url", "down")] * (CFG["outage_retries"] + 1)
    checker, client = checker_with(tmp_path, outages)
    result = checker.check(GOOD)
    assert result.status == OUTAGE and not result.passed
    assert client.calls == CFG["outage_retries"] + 1
    assert not list(tmp_path.iterdir())


def test_outage_then_success(tmp_path):
    checker, client = checker_with(tmp_path, [axle.AxleInternalError("boom"), ok_response()])
    assert checker.check(GOOD).status == OK
    assert client.calls == 2


def test_timeout_and_resource_are_failures_not_outages(tmp_path):
    checker, _ = checker_with(tmp_path, [axle.LeanTimeout("slow"), axle.LeanResourceExceeded("oom")])
    assert checker.check("a").status == TIMEOUT
    assert checker.check("b").status == RESOURCE


def test_sorry_in_failed_declarations_still_passes(tmp_path):
    checker, _ = checker_with(tmp_path, [ok_response(okay=True, failed=["t"])])
    assert checker.check(SORRY).passed


def test_cache_hit_makes_no_second_call(tmp_path):
    checker, client = checker_with(tmp_path, [ok_response(okay=False, errors=["bad"])])
    first = checker.check(BROKEN)
    second = checker.check(BROKEN)
    assert first == second and first.status == LEAN_ERROR
    assert client.calls == 1


def test_cache_key_depends_on_content(tmp_path):
    checker, _ = checker_with(tmp_path, [])
    assert checker.cache_path(GOOD) != checker.cache_path(SORRY)
    assert checker.cache_path(GOOD) == checker.cache_path(GOOD)


load_env()
live = pytest.mark.skipif(not os.environ.get("AXLE_API_KEY"), reason="no AXLE_API_KEY")


@pytest.mark.live
@live
def test_live_known_good_passes():
    assert AxleChecker(CFG).check(GOOD).status == OK


@pytest.mark.live
@live
def test_live_sorry_statement_passes():
    result = AxleChecker(CFG).check(SORRY)
    assert result.status == OK
    assert result.failed_declarations == ["t"]


@pytest.mark.live
@live
def test_live_broken_fails():
    result = AxleChecker(CFG).check(BROKEN)
    assert result.status == LEAN_ERROR
    assert result.errors
