"""Chunk 7: candidate ordering and summary, the compile-error buckets, and the writeup number check."""
import json

from src.axle_check import CheckResult
from src.chunk7 import candidate_files, candidate_summary, check_numbers, compile_errors, em_dashes, error_bucket, numbers_in


def test_candidate_files_follow_gepa_order(tmp_path):
    (tmp_path / "candidates").mkdir()
    (tmp_path / "candidates.json").write_text(json.dumps({"candidates": [{"instructions": "seed"}, {"instructions": "new"}]}))
    for name, instr in (("aa.jsonl", "new"), ("bb.jsonl", "seed")):
        (tmp_path / "candidates" / name).write_text(json.dumps({"instructions": instr}) + "\n" + json.dumps({"item_id": "v1"}) + "\n")
    assert [c for c, _ in candidate_files(tmp_path)] == [0, 1]


def test_candidate_summary_leaves_missing_truth_out():
    rows = [{"run_id": "B_s0", "candidate": 0, "judge_score": s, "truth_label": t, "truth_source": src}
            for s, t, src in ((1, "faithful", "ref_judge"), (1, "unfaithful", "ref_judge"), (0, None, "ref_judge_missing"), (0, "unfaithful", "compile"))]
    s = candidate_summary(rows)["B_s0"][0]
    assert s["judge"] == 50 and abs(s["truth"] - 100 / 3) < 1e-9 and s["truth_missing"] == 1 and s["outages"] == 0


def test_error_buckets():
    assert error_bucket("lean_error", ["-:8:6: error(lean.unknownIdentifier): Unknown identifier `Simple`"]) == "unknown name"
    assert error_bucket("lean_error", ["-:7:77: error: Application type mismatch: The argument"]) == "type mismatch"
    assert error_bucket("lean_error", ["error: failed to synthesize\n  HAdd"]) == "failed to synthesize instance"
    assert error_bucket("lean_error", ["error: unexpected token ','; expected '↦', '=>'"]) == "syntax"
    assert error_bucket("lean_error", ["error(lean.invalidField): Invalid field `norm`: The environment"]) == "unknown name"
    assert error_bucket("lean_error", ["-:3:4: error: type expected, got"]) == "type or function expected"
    assert error_bucket("lean_error", ["-:3:4: error: expected token"]) == "syntax"
    assert error_bucket("lean_error", ["error: something else"]) == "other"
    assert error_bucket("timeout", []) == "timeout"


def test_compile_errors_counts_format_failures_and_status_changes():
    class Checker:
        def check_many(self, contents):
            return [CheckResult("lean_error", ["Unknown identifier `X`"]), CheckResult("ok", [])]
    items = {"i1": {"header": "import Mathlib", "helper": ""}, "i2": {"header": "import Mathlib", "helper": ""}}
    rows = [{"arm": "A", "dataset": "test", "item_id": "i1", "compiled": False, "normalized": "theorem candidate : True := by sorry", "compile_status": "lean_error"},
            {"arm": "A", "dataset": "test", "item_id": "i2", "compiled": False, "normalized": "theorem candidate : True := by sorry", "compile_status": "lean_error"},
            {"arm": "A", "dataset": "test", "item_id": "i2", "compiled": False, "normalized": None, "compile_status": None},
            {"arm": "A", "dataset": "test", "item_id": "i1", "compiled": True, "normalized": "x", "compile_status": "ok"}]
    a = compile_errors(rows, Checker(), items)["A"]
    assert (a["outputs"], a["not_compiled"], a["format_failures"], a["rechecked"], a["recheck_status_differs"]) == (4, 3, 1, 2, 1)
    assert a["buckets"] == {"unknown name": {"count": 1, "share": 100.0, "share_of_outputs": 25.0}}


def test_number_check_catches_wrong_unlisted_and_precision():
    data = {"q": {"est": 2.834, "ci": [-0.404, 6.61]}, "rate": 0.899}
    text = "Q1 was +2.8 points [-0.4, 6.6] in a 95% interval on Qwen3-8B; agreement 89.9%. See [paper](https://arxiv.org/abs/2507.19457)."
    entries = [{"value": "2.8", "source": "r", "path": "q.est"}, {"value": "-0.4", "source": "r", "path": "q.ci.0"},
               {"value": "6.6", "source": "r", "path": "q.ci.1"}, {"value": "89.9", "source": "r", "path": "rate", "scale": 100},
               {"value": "95", "why": "interval level"}]
    assert numbers_in(text) == ["+2.8", "-0.4", "6.6", "95", "89.9"]
    assert check_numbers(text, entries, lambda s: data)["ok"]
    assert check_numbers(text, entries[1:], lambda s: data)["unlisted"] == ["2.8"]
    bad = check_numbers(text.replace("6.6", "6.7"), entries[:2] + [{"value": "6.7", "source": "r", "path": "q.ci.1"}] + entries[3:], lambda s: data)
    assert [w["actual"] for w in bad["wrong"]] == ["6.6"] and not bad["ok"]
    assert check_numbers("value 2.83", [{"value": "2.83", "source": "r", "path": "q.est"}], lambda s: data)["ok"]
    assert numbers_in("grew to 1,677 words on 2026-10-24 (Lean 4)") == ["1,677", "4"]
    assert check_numbers("1,677 words", [{"value": "1,677", "source": "r", "path": "w"}], lambda s: {"w": 1677})["ok"]
    assert check_numbers("value -0.0", [{"value": "-0.0", "source": "r", "path": "z"}], lambda s: {"z": -0.01})["wrong"]


def test_em_dash_scan(tmp_path):
    (tmp_path / "a.md").write_text("fine - here")
    (tmp_path / "b.md").write_text("bad \u2014 here")
    assert em_dashes(sorted(tmp_path.glob("*.md"))) == {str(tmp_path / "b.md"): 1}
