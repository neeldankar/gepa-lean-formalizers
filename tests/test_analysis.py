import copy
import json

import numpy as np

import pytest

from src import analysis
from src.config import load_config
from src.fake_results import fake_rows

CFG = copy.deepcopy(load_config())
CFG["analysis"]["bootstrap_resamples"] = 2000  # enough for the checks; the real run uses config's 10,000


@pytest.fixture(scope="module")
def planted():
    return analysis.analyze(fake_rows(effect_points=10, judge_extra_points=8), CFG)


def test_bootstrap_recovers_planted_effect(planted):
    q1 = planted["confirmatory"]["contrasts"]["Q1"]
    lo, hi = q1["ci"]
    assert lo <= 10 <= hi and lo > 0
    assert q1["estimate"] == pytest.approx(round(247 * 0.10) / 247 * 100)


def test_judge_gap_recovered_as_descriptive(planted):
    d = planted["confirmatory"]["descriptive"]
    q = d["judge_gain_minus_truth_gain_qwen3-8b"]
    assert q["ci"][0] > 0 and q["estimate"] == pytest.approx(round(247 * 0.08) / 247 * 100, abs=0.01)
    assert d["judge_gain_minus_truth_gain_reform-8b"]["estimate"] == 0 and "decision" not in q


def test_q3_false_positive_rate_planted(planted):
    # B's judge says faithful on 8% more items whose truth is unfaithful; everything compiles.
    c = planted["confirmatory"]["contrasts"]
    assert c["Q3_qwen3-8b"]["estimate"] == pytest.approx(round(247 * 0.08) / 247 * 100)
    assert c["Q3_qwen3-8b"]["ci"][0] > 0 and c["Q3_qwen3-8b"]["decision"] == "effect"
    assert c["Q3_reform-8b"]["estimate"] == 0 and c["Q3_reform-8b"]["ci"] == [0.0, 0.0]
    assert planted["confirmatory"]["per_arm_intervals"]["A:fpr"]["estimate"] == 0
    assert not any(k.endswith((":fp", ":compiled")) for k in planted["confirmatory"]["per_arm_intervals"])


def test_false_positive_rate_exact_uncompiled_out_of_denominator():
    def row(arm, seed, i, compiled, judge, truth):
        return {"arm": arm, "gepa_seed": seed, "dataset": "test", "item_id": f"t{i}", "sample": 0, "outage": False,
                "compiled": compiled, "judge_score": judge, "truth_label": truth}
    rows = [row("A", None, i, c, j, "unfaithful") for i, (c, j) in enumerate([(True, 1), (True, 0), (False, 0), (False, 0)])]
    # B seed 0: 1 false positive of 4 compiled (item 0 is truly faithful) = 25; seed 1: 1 of 1 compiled = 100
    rows += [row("B", 0, i, True, j, t) for i, (j, t) in enumerate([(1, "faithful"), (1, "unfaithful"), (0, "unfaithful"), (0, "unfaithful")])]
    rows += [row("B", 1, i, i == 0, int(i == 0), "unfaithful") for i in range(4)]
    mats, _ = analysis.matrices(rows, "test")
    means = analysis.arm_means(mats)
    assert means[("A", "fpr")] == pytest.approx(50.0) and means[("B", "fpr")] == pytest.approx(62.5)
    assert analysis.contrast_value(means, analysis.CONTRASTS["Q3_qwen3-8b"]) == pytest.approx(12.5)


def test_no_planted_effect_covers_zero():
    r = analysis.analyze(fake_rows(effect_points=0, seed=1), CFG)
    for name in ("Q1", "Q2", "Q3_qwen3-8b"):
        lo, hi = r["confirmatory"]["contrasts"][name]["ci"]
        assert lo <= 0 <= hi, name


@pytest.mark.parametrize("estimate,ci,expected", [
    (8.0, [3.0, 13.0], "effect"),
    (-8.0, [-13.0, -3.0], "effect"),
    (3.0, [1.0, 5.0], "no meaningful effect"),   # excludes 0, but the whole interval is within +-5
    (3.0, [0.5, 5.5], "inconclusive"),           # excludes 0, too small, not within +-5
    (1.0, [-3.0, 4.0], "no meaningful effect"),
    (2.0, [-4.0, 9.0], "inconclusive"),
    (6.0, [-1.0, 13.0], "inconclusive"),
])
def test_decision_rule(estimate, ci, expected):
    assert analysis.decide(estimate, ci, 5) == expected


def test_seed_level_rates(planted):
    rates = planted["confirmatory"]["arm_truth_rates"]
    assert len(rates["B"]["per_seed"]) == 3 and len(rates["A"]["per_seed"]) == 1


def test_end_to_end_writes_results_and_both_figures(tmp_path):
    results = analysis.analyze(fake_rows(minif2f_items=50), CFG)
    (tmp_path / "results.json").write_text(json.dumps(results))
    analysis.figures(results, tmp_path / "figures")
    assert (tmp_path / "figures/truth_by_arm.png").stat().st_size > 1000
    assert (tmp_path / "figures/judge_vs_truth_gain.png").stat().st_size > 1000
    assert results["exploratory"]["note"] == "exploratory" and "minif2f_transfer" in results["exploratory"]
    assert set(results["alongside"]["compile_and_memorization"]) == {"A", "B", "C", "D"}


FLIP = {"faithful": "unfaithful", "unfaithful": "faithful"}


def hand_labeled(tmp_path, rows, n_items, label=lambda arm, i, truth: truth, extra=()):
    """Random part: items test_000.. labeled in all four core arms (seed i % 3 for B and D)."""
    truth = {(r["arm"], r["item_id"], r["gepa_seed"]): r["truth_label"] for r in rows if r["dataset"] == "test"}
    sample, lines = [], []
    for i in range(n_items):
        for arm in analysis.CORE:
            gseed = i % 3 if arm in ("B", "D") else None
            item = f"test_{i:03d}"
            sample.append({"label_id": f"h{len(sample)}", "arm": arm, "item_id": item, "gepa_seed": gseed,
                           "sample": 0, "parts": ["random"]})
            lines.append(f"{sample[-1]['label_id']},{label(arm, i, truth[(arm, item, gseed)])}\n")
    for s in extra:
        sample.append({"label_id": f"h{len(sample)}", "sample": 0, **s})
        lines.append(f"{sample[-1]['label_id']},{s.get('_label', 'faithful')}\n")
    (tmp_path / "labels.csv").write_text("label_id,label\n" + "".join(lines))
    (tmp_path / "sample.jsonl").write_text("".join(json.dumps(s) + "\n" for s in sample))
    return analysis.read_labels(tmp_path / "labels.csv", tmp_path / "sample.jsonl")


def test_hand_check_agreement(tmp_path):
    rows = fake_rows(n_items=40)
    labeled = hand_labeled(tmp_path, rows, 10, lambda arm, i, t: FLIP[t] if arm == "A" and i >= 8 else t)
    hc = analysis.hand_check(rows, labeled, 200, 0)
    assert hc["judge_agreement_random_part"]["all"] == {"agree": 38, "n": 40, "rate": 95.0}
    assert hc["judge_agreement_random_part"]["A"] == {"agree": 8, "n": 10, "rate": 80.0}
    assert hc["random_items"] == hc["random_items_paired"] == 10 and hc["items_dropped"] == 0


def test_hand_check_bootstrap_is_paired(tmp_path):
    # B labeled exactly like A on every item: paired, every resample gives 0; unpaired would not.
    rows = fake_rows(n_items=60, seed=3)
    truth_a = {r["item_id"]: r["truth_label"] for r in rows if r["arm"] == "A"}
    labeled = hand_labeled(tmp_path, rows, 60, lambda arm, i, t: truth_a[f"test_{i:03d}"] if arm == "B" else t)
    q1 = analysis.hand_check(rows, labeled, 500, 0)["contrasts_random_part_hand_labels"]["Q1"]
    assert q1["estimate"] == 0 and q1["ci"] == [0.0, 0.0]


def test_hand_check_recovers_planted_effect(tmp_path):
    rows = fake_rows(n_items=100, effect_points=10)
    labeled = hand_labeled(tmp_path, rows, 100)
    q1 = analysis.hand_check(rows, labeled, 1000, 0)["contrasts_random_part_hand_labels"]["Q1"]
    rate = {arm: 100 * sum(x["label"] == "faithful" for x in labeled if x["arm"] == arm) / 100 for arm in ("A", "B")}
    assert q1["estimate"] == pytest.approx(rate["B"] - rate["A"]) and q1["estimate"] == pytest.approx(10)
    assert q1["ci"][0] > 0


def test_hand_check_unsure_drops_item_from_contrasts_only(tmp_path):
    rows = fake_rows(n_items=40)
    labeled = hand_labeled(tmp_path, rows, 10, lambda arm, i, t: "unsure" if arm == "C" and i == 4 else t)
    hc = analysis.hand_check(rows, labeled, 200, 0)
    assert hc["random_items"] == 10 and hc["random_items_paired"] == 9 and hc["items_dropped"] == 1
    assert hc["unsure"] == 1 and hc["judge_agreement_random_part"]["all"]["n"] == 39


def test_output_in_both_parts_counts_in_both(tmp_path):
    rows = fake_rows(n_items=40)
    truth = {r["item_id"]: r["truth_label"] for r in rows if r["arm"] == "C"}
    both = {"arm": "C", "item_id": "test_020", "gepa_seed": None, "parts": ["random", "disagreement"],
            "_label": truth["test_020"]}
    only = {"arm": "A", "item_id": "test_021", "gepa_seed": None, "parts": ["disagreement"]}
    hc = analysis.hand_check(rows, hand_labeled(tmp_path, rows, 10, extra=(both, only)), 200, 0)
    assert hc["disagreement_part"] == 2
    assert hc["judge_agreement_random_part"]["C"]["n"] == 11 and hc["judge_agreement_random_part"]["all"]["n"] == 41
    assert hc["random_items"] == 11 and hc["random_items_paired"] == 10  # test_020 has only arm C


def test_seed_resampling_widens_interval_when_seeds_disagree():
    same = fake_rows(effect_points=10)
    # B's seeds now plant 0, 10 and 20 points (mean 10) instead of 10 each
    spread = [r for r in same if r["arm"] != "B"]
    for gseed, eff in ((0, 0), (1, 10), (2, 20)):
        spread += [r for r in fake_rows(effect_points=eff) if r["arm"] == "B" and r["gepa_seed"] == gseed]
    width = {}
    for name, rows in (("same", same), ("spread", spread)):
        q1 = analysis.analyze(rows, CFG)["confirmatory"]["contrasts"]["Q1"]
        width[name] = q1["ci"][1] - q1["ci"][0]
        assert q1["estimate"] == pytest.approx(round(247 * 0.10) / 247 * 100, abs=0.5)
    assert width["spread"] > width["same"] + 2


def test_hand_check_computes_q3_from_hand_labels(tmp_path):
    rows = fake_rows(n_items=100, judge_extra_points=8)
    labeled = hand_labeled(tmp_path, rows, 100)  # hand labels equal the truth labels
    hc = analysis.hand_check(rows, labeled, 500, 0)["contrasts_random_part_hand_labels"]
    judge_b = {r["item_id"]: r["judge_score"] for r in rows if r["arm"] == "B" and r["gepa_seed"] == 0}
    truth_b = {r["item_id"]: r["truth_label"] for r in rows if r["arm"] == "B" and r["gepa_seed"] == 0}
    expected = 100 * sum(judge_b[i] == 1 and truth_b[i] == "unfaithful" for i in judge_b) / 100
    assert hc["Q3_qwen3-8b"]["estimate"] == pytest.approx(expected) and expected > 0


def split_rows():
    """A: compiles 50 of 100, 20 faithful (f = 40%). B: compiles all 100, 40 faithful (f = 40%): a compile-only gain.
    C: compiles 60, 30 faithful. D: compiles 60, 45 faithful: a meaning-only gain."""
    rows = []
    def add(arm, seed, compiled, faithful):
        for i in range(100):
            c, f = i < compiled, i < faithful
            rows.append({"arm": arm, "gepa_seed": seed, "dataset": "test", "item_id": f"t{i:03d}", "sample": 0,
                         "outage": False, "compiled": c, "judge_score": int(f), "truth_label": "faithful" if f else "unfaithful",
                         "truth_source": "ref_judge" if c else "compile", "format_failure": False, "certified": False,
                         "ref_verdict": ("faithful" if f else "unfaithful") if c else None, "ref_error_tag": None, "memorized": []})
    add("A", None, 50, 20)
    for s in (0, 1, 2):
        add("B", s, 100, 40)
        add("D", s, 60, 45)
    add("C", None, 60, 30)
    return rows


def test_truth_gain_split_is_exact_and_attributes_correctly():
    mats, _ = analysis.matrices(split_rows(), "test")
    m = analysis.arm_means(mats)
    ab = analysis.decomposition(m, "A", "B")
    assert ab["total"] == pytest.approx(20) and ab["compile_part"] == pytest.approx(20) and ab["meaning_part"] == pytest.approx(0)
    cd = analysis.decomposition(m, "C", "D")
    assert cd["total"] == pytest.approx(15) and cd["compile_part"] == pytest.approx(0) and cd["meaning_part"] == pytest.approx(15)
    # the identity holds on every bootstrap resample, not only at the point estimate
    rng = np.random.default_rng(0)
    for _ in range(50):
        idx = rng.integers(0, 100, 100)
        seeds = {a: rng.integers(0, d["truth"].shape[0], d["truth"].shape[0]) for a, d in mats.items()}
        d = analysis.decomposition(analysis.arm_means(mats, idx, seeds), "A", "B")
        assert d["compile_part"] + d["meaning_part"] == pytest.approx(d["total"])


def test_split_reported_with_intervals():
    r = analysis.analyze(split_rows(), CFG)
    s = r["alongside"]["truth_gain_split"]
    assert s["A_to_B"]["compile_part"]["estimate"] == pytest.approx(20) and len(s["A_to_B"]["compile_part"]["ci"]) == 2
    assert s["C_to_D"]["meaning_part"]["estimate"] == pytest.approx(15)


def test_truth_source_shares():
    stats = analysis.compile_stats(split_rows(), "test")
    assert stats["A"]["truth_source_share"] == {"certificate": 0.0, "ref_judge": 50.0, "ref_judge_missing": 0.0,
                                                 "compile_failure": 50.0, "of_which_format": 0.0}


def test_missing_verdicts_drop_out_of_rates_and_are_counted():
    rows = split_rows()
    a = [r for r in rows if r["arm"] == "A"]
    # A items 0 and 1: compiled, faithful, judge score 1. Item 0 loses both judges; item 1 only the opt judge.
    a[0].update(judge_score=None, judge_missing=True, ref_missing=True, ref_verdict="missing", truth_label=None,
                truth_source="ref_judge_missing")
    a[1].update(judge_score=None, judge_missing=True)
    mats, _ = analysis.matrices(rows, "test")
    m = analysis.arm_means(mats)
    assert m[("A", "truth")] == pytest.approx(100 * 19 / 99)    # 19 faithful of the 99 items with a truth label
    assert m[("A", "judge")] == pytest.approx(100 * 18 / 98)    # judge score over the 98 items with a judge verdict
    assert m[("A", "c")] * m[("A", "f")] / 100 == pytest.approx(m[("A", "truth")])  # the split stays exact
    stats = analysis.compile_stats(rows, "test")["A"]
    assert (stats["missing_opt_judge"], stats["missing_ref_judge"], stats["missing_truth_label"]) == (2, 1, 1)
    assert stats["outages"] == 0 and stats["outputs"] == 100   # missing is not an outage


def test_reference_judge_false_positives_and_negatives(tmp_path):
    rows = fake_rows(n_items=40)
    # A: 2 items where the hand label says unfaithful but the judge said faithful (false positives), 1 the other way
    truth_a = {r["item_id"]: r["truth_label"] for r in rows if r["arm"] == "A"}
    fp_items = [i for i in range(10) if truth_a[f"test_{i:03d}"] == "faithful"][:2]
    fn_items = [i for i in range(10) if truth_a[f"test_{i:03d}"] == "unfaithful"][:1]
    def label(arm, i, t):
        return FLIP[t] if arm == "A" and i in fp_items + fn_items else t
    hc = analysis.hand_check(rows, hand_labeled(tmp_path, rows, 10, label), 200, 0)
    e = hc["judge_errors_random_part"]["A"]
    assert (e["false_positive"], e["false_negative"], e["n"]) == (len(fp_items), len(fn_items), 10)
    assert hc["judge_errors_random_part"]["all"]["false_positive"] == len(fp_items)


def test_missing_generation_rows_are_in_no_rate_and_are_counted():
    # Deviation 3: an arm F call that failed after its retries is missing for that item.
    import numpy as np
    from src import analysis
    from src.final_eval import missing_row
    ok = {"arm": "F", "run_id": None, "gepa_seed": None, "dataset": "test", "item_id": "pnv_1", "sample": 0,
          "compiled": True, "format_failure": False, "truth_label": "faithful", "truth_source": "certificate",
          "judge_score": 1, "judge_missing": False, "ref_missing": False, "certified": True, "ref_verdict": "faithful",
          "ref_error_tag": None, "memorized": [], "outage": False, "generation_missing": False}
    gone = missing_row("F", None, None, "test", {"id": "pnv_2"}, 0, "LLMError: gave up after 5 attempts")
    stats = analysis.compile_stats([ok, gone], "test")["F"]
    assert stats["outputs"] == 1 and stats["compile_rate"] == 100 and stats["format_failure_rate"] == 0
    assert stats["missing_generation"] == 1 and stats["missing_truth_label"] == 0
    for f in (analysis.truth_value, analysis.judge_value, analysis.false_positive):
        assert np.isnan(f(gone))
    mats, items = analysis.matrices([ok, gone], "test")
    assert items == ["pnv_1", "pnv_2"]
    assert all(np.isnan(mats["F"][k][0][1]) for k in ("truth", "judge", "fp", "compiled"))
    assert mats["F"]["truth"][0][0] == 100
