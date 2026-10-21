"""Fake final-eval rows with planted effects, for analysis tests and the chunk 3 dry run only."""
import numpy as np


def fake_rows(n_items=247, effect_points=10.0, judge_extra_points=0.0, seed=0, minif2f_items=0):
    """Truth: A ~ 30%; B = A plus `effect_points` more items made faithful (same in every seed);
    C = D = 40%. Judge: equals truth, plus `judge_extra_points` more items in B only."""
    rng = np.random.default_rng(seed)
    rows = []
    for dataset, n in (("test", n_items), ("minif2f", minif2f_items)):
        if not n:
            continue
        base = rng.random(n) < 0.30
        unfaithful = np.flatnonzero(~base)
        flip = unfaithful[: round(n * effect_points / 100)]
        b = base.copy()
        b[flip] = True
        judge_flip = np.flatnonzero(~b)[: round(n * judge_extra_points / 100)]
        b_judge = b.copy()
        b_judge[judge_flip] = True
        c = rng.random(n) < 0.40
        arms = {"A": [(None, base, base)], "B": [(s, b, b_judge) for s in (0, 1, 2)],
                "C": [(None, c, c)], "D": [(s, c, c) for s in (0, 1, 2)]}
        for arm, versions in arms.items():
            for gseed, truth, judge in versions:
                for i in range(n):
                    rows.append({
                        "arm": arm, "run_id": None if gseed is None else f"{arm}_s{gseed}", "gepa_seed": gseed,
                        "dataset": dataset, "item_id": f"{dataset}_{i:03d}", "sample": 0,
                        "compiled": True, "format_failure": False, "outage": False,
                        "truth_label": "faithful" if truth[i] else "unfaithful",
                        "judge_score": int(judge[i]), "certified": False, "truth_source": "ref_judge",
                        "ref_verdict": "faithful" if truth[i] else "unfaithful",
                        "ref_error_tag": None if truth[i] else "Missing premise", "memorized": [],
                    })
    return rows
