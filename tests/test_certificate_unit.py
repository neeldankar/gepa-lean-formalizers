from types import SimpleNamespace

from src.axle_check import CheckResult
from src.scoring.certificate import (DIRECTIONS, TACTICS, attempt_name, certificate, closed_prop,
                                     direction_content)

ITEM = {"header": "import Mathlib", "helper": "def g := 1"}
CAND = "theorem candidate (n : ℕ) (h : 1 < n) : n ≠ 0 := by\n  sorry"
REF = "theorem Ref_1 (n : ℕ) (hn : n > 1) : n ≠ 0 := by\n  sorry"


def test_closed_prop():
    assert closed_prop("theorem candidate {G : Type*} [Group G] (a : G) : a = a := by\n  sorry") == "∀ {G : Type*} [Group G] (a : G), a = a"
    assert closed_prop("theorem candidate : 1 = 1 := by\n  sorry") == "1 = 1"
    assert closed_prop("theorem candidate (h : x ∈ ({1} : Set ℕ)) : x = 1 := by sorry") == "∀ (h : x ∈ ({1} : Set ℕ)), x = 1"


def test_each_file_declares_only_its_hypothesis_theorem():
    c2r, _ = direction_content(ITEM, "c2r", CAND, REF)
    r2c, _ = direction_content(ITEM, "r2c", CAND, REF)
    assert "theorem cert_cand " in c2r and "cert_ref" not in c2r and "Ref_1" not in c2r
    assert "theorem cert_ref " in r2c and "cert_cand" not in r2c and "theorem candidate" not in r2c


def test_autoimplicit_off_for_candidate_side_only():
    c2r, spans = direction_content(ITEM, "c2r", CAND, REF)
    assert "set_option autoImplicit false in\ntheorem cert_cand" in c2r
    assert "autoImplicit" not in c2r.split("theorem cert_true")[1]  # reference target: as shipped
    r2c, _ = direction_content(ITEM, "r2c", CAND, REF)
    assert "autoImplicit" not in r2c.split("theorem cert_true")[0]  # reference hypothesis: as shipped
    assert r2c.count("set_option autoImplicit false in") == 2 * len(TACTICS)


def test_spans_point_at_each_attempt():
    text, spans = direction_content(ITEM, "c2r", CAND, REF)
    lines = text.split("\n")
    for name, (a, b) in spans.items():
        block = "\n".join(lines[a - 1:b])
        assert f"theorem {name} " in block and block.startswith("set_option maxHeartbeats")


class LineChecker:
    """Fails exactly the attempts whose names are in `failed`, by reporting an error on their line."""

    def __init__(self, failed, extra_errors=()):
        self.failed, self.extra = set(failed), list(extra_errors)

    def check(self, content):
        errors = list(self.extra)
        for i, line in enumerate(content.split("\n"), 1):
            m = line.startswith("theorem cert_") and line.split()[1]
            if m in self.failed:
                errors.append(f"-:{i}:8: error: failed")
        return CheckResult("lean_error" if errors else "ok", errors, [])


def names(pred):
    return {attempt_name(d, k, h) for d in DIRECTIONS for k in range(len(TACTICS)) for h in (True, False) if pred(d, k, h)}


def test_both_directions_needing_the_hypothesis_certify():
    out = certificate(LineChecker(names(lambda d, k, h: not h)), ITEM, CAND, REF)
    assert out["certified"] and out["directions"]["c2r"] == TACTICS


def test_proof_from_scratch_does_not_count():
    out = certificate(LineChecker(names(lambda d, k, h: d == "c2r" and not h)), ITEM, CAND, REF)
    assert not out["certified"] and out["directions"]["r2c"] == [] and out["discarded"]["r2c"] == TACTICS


def test_error_in_hypothesis_theorem_means_no_certificate():
    out = certificate(LineChecker(set(), extra_errors=["-:5:3: error: unknown identifier"]), ITEM, CAND, REF)
    assert out["status"] == "setup_error" and not out["certified"]


def test_outage_passes_through():
    checker = SimpleNamespace(check=lambda c: CheckResult("outage", ["down"]))
    out = certificate(checker, ITEM, CAND, REF)
    assert out["status"] == "outage" and not out["certified"]


def test_reference_options_reach_every_attempt_and_the_hypothesis():
    ref = "set_option maxRecDepth 2048 in\ntheorem R : 1 = 1 := by\n  sorry"
    c2r, spans = direction_content(ITEM, "c2r", CAND, ref)
    r2c, _ = direction_content(ITEM, "r2c", CAND, ref)
    assert c2r.count("set_option maxRecDepth 2048 in") == 2 * len(TACTICS)
    assert "set_option maxRecDepth 2048 in\ntheorem cert_ref " in r2c
