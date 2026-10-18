from types import SimpleNamespace

from src.axle_check import CheckResult
from src.scoring.certificate import TACTICS, attempt_name, certificate, closed_prop

ITEM = {"header": "import Mathlib", "helper": ""}


def test_closed_prop():
    assert closed_prop("theorem candidate {G : Type*} [Group G] (a : G) : a = a := by\n  sorry") == "∀ {G : Type u} [Group G] (a : G), a = a"
    assert closed_prop("theorem candidate : 1 = 1 := by\n  sorry") == "1 = 1"
    assert closed_prop("theorem candidate (h : x ∈ ({1} : Set ℕ)) : x = 1 := by sorry") == "∀ (h : x ∈ ({1} : Set ℕ)), x = 1"


class FakeChecker:
    def __init__(self, failed):
        self.failed = failed

    def check(self, content):
        return CheckResult("lean_error" if self.failed else "ok", [], sorted(self.failed))


def all_names():
    return {attempt_name(d, k, h) for d in ("c2r", "r2c") for k in range(len(TACTICS)) for h in (True, False)}


def test_both_directions_with_hypothesis_needed_certify():
    failed = {n for n in all_names() if n.endswith("_noh") or "_1_" in n}
    out = certificate(FakeChecker(failed), ITEM, "theorem candidate : 1 = 1 := by sorry", "theorem candidate : 1 = 1 := by sorry")
    assert out["certified"]


def test_proof_from_scratch_does_not_count():
    failed = {n for n in all_names() if n.startswith("cert_c2r")}  # r2c proves with and without hcert
    out = certificate(FakeChecker(failed), ITEM, "theorem candidate : 1 = 1 := by sorry", "theorem candidate : 2 = 2 := by sorry")
    assert not out["certified"] and out["directions"]["r2c"] == [] and out["discarded"]["r2c"]


def test_outage_passes_through():
    checker = SimpleNamespace(check=lambda c: CheckResult("outage", ["down"]))
    out = certificate(checker, ITEM, "theorem candidate : 1 = 1 := by sorry", "theorem candidate : 1 = 1 := by sorry")
    assert out["status"] == "outage" and not out["certified"]
