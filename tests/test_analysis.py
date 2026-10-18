import copy
import json

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


def test_judge_gap_recovered(planted):
    q3 = planted["confirmatory"]["contrasts"]["Q3_qwen3-8b"]
    assert q3["ci"][0] > 0 and q3["estimate"] == pytest.approx(round(247 * 0.08) / 247 * 100, abs=0.01)
    assert planted["confirmatory"]["contrasts"]["Q3_reform-8b"]["estimate"] == 0


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
