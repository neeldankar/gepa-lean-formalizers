"""Chunk 6 analysis, written in chunk 3 before any results exist (prereg Analysis plan).

All rates are in points (0 to 100). A per-item value is the mean over samples. For GEPA arms
(several seeds), the arm's value is the mean over seeds. The paired bootstrap resamples test items
(the same draw for every arm) and, within each GEPA arm, resamples its seeds with replacement.

Confirmatory, on the test split:
  Q1 = B - A (truth)
  Q2 = (D - C) - (B - A) (truth)
  Q3 = (judge gain) - (truth gain), for Qwen3-8B (A to B) and ReForm-8B (C to D)
Decision rule (threshold T points): "effect" if the interval excludes 0 and |estimate| >= T, in
either direction (the estimate keeps its sign); "no meaningful effect" if the whole interval lies within [-T, T]; otherwise "inconclusive".
"""
import csv
import json
from collections import Counter, defaultdict

import numpy as np

CORE = ("A", "B", "C", "D")
CONTRASTS = {
    "Q1": {"truth": {"B": 1, "A": -1}},
    "Q2": {"truth": {"D": 1, "C": -1, "B": -1, "A": 1}},
    "Q3_qwen3-8b": {"judge": {"B": 1, "A": -1}, "truth": {"B": -1, "A": 1}},
    "Q3_reform-8b": {"judge": {"D": 1, "C": -1}, "truth": {"D": -1, "C": 1}},
}
EXPLORATORY_CONTRASTS = {k: CONTRASTS[k] for k in ("Q1", "Q2")}


def truth_value(row):
    return 1.0 if row["truth_label"] == "faithful" else 0.0


def judge_value(row):
    return float(row["judge_score"] or 0)


def matrices(rows, dataset, items=None, exclude=frozenset()):
    """{arm: {"truth"/"judge": array (seeds x items)}} over a shared item order."""
    rows = [r for r in rows if r["dataset"] == dataset and not r.get("outage")]
    item_ids = sorted(items if items is not None else {r["item_id"] for r in rows} - set(exclude))
    pos = {i: k for k, i in enumerate(item_ids)}
    acc = defaultdict(lambda: defaultdict(list))
    for r in rows:
        if r["item_id"] in pos:
            acc[(r["arm"], r["gepa_seed"])][r["item_id"]].append(r)
    out = defaultdict(lambda: {"truth": [], "judge": []})
    for (arm, seed), by_item in sorted(acc.items(), key=lambda kv: (kv[0][0], -1 if kv[0][1] is None else kv[0][1])):
        t, j = np.full(len(item_ids), np.nan), np.full(len(item_ids), np.nan)
        for i, rs in by_item.items():
            t[pos[i]] = np.mean([truth_value(r) for r in rs])
            j[pos[i]] = np.mean([judge_value(r) for r in rs])
        out[arm]["truth"].append(t)
        out[arm]["judge"].append(j)
    return {arm: {k: np.array(v) * 100 for k, v in d.items()} for arm, d in out.items()}, item_ids


def arm_means(mats, idx=None, seed_draws=None):
    """{(arm, score): mean}, optionally on resampled items and seeds."""
    out = {}
    for arm, d in mats.items():
        for score, m in d.items():
            seeds = seed_draws[arm] if seed_draws else np.arange(m.shape[0])
            sub = m[seeds] if idx is None else m[np.ix_(seeds, idx)]
            out[(arm, score)] = float(np.nanmean(sub))
    return out


def contrast_value(means, spec):
    return sum(w * means[(arm, score)] for score, arms in spec.items() for arm, w in arms.items())


def bootstrap(mats, contrasts, resamples, seed):
    """{name: {"estimate", "ci": [lo, hi]}} plus per-arm means with intervals."""
    n = next(iter(mats.values()))["truth"].shape[1]
    rng = np.random.default_rng(seed)
    point = arm_means(mats)
    draws = defaultdict(list)
    arm_draws = defaultdict(list)
    for _ in range(resamples):
        idx = rng.integers(0, n, n)
        seed_draws = {arm: rng.integers(0, d["truth"].shape[0], d["truth"].shape[0]) for arm, d in mats.items()}
        means = arm_means(mats, idx, seed_draws)
        for name, spec in contrasts.items():
            if all(arm in mats for s in spec.values() for arm in s):
                draws[name].append(contrast_value(means, spec))
        for key, v in means.items():
            arm_draws[key].append(v)
    result = {}
    for name, spec in contrasts.items():
        if name in draws:
            lo, hi = np.percentile(draws[name], [2.5, 97.5])
            result[name] = {"estimate": contrast_value(point, spec), "ci": [float(lo), float(hi)]}
    per_arm = {f"{arm}:{score}": {"estimate": point[(arm, score)], "ci": [float(x) for x in np.percentile(v, [2.5, 97.5])]}
               for (arm, score), v in arm_draws.items()}
    return result, per_arm


def decide(estimate, ci, threshold):
    lo, hi = ci
    if (lo > 0 or hi < 0) and abs(estimate) >= threshold:
        return "effect"
    if lo >= -threshold and hi <= threshold:
        return "no meaningful effect"
    return "inconclusive"


def per_seed_rates(mats):
    return {arm: {"per_seed": [float(np.nanmean(s)) for s in d["truth"]], "mean": float(np.nanmean(d["truth"]))}
            for arm, d in mats.items()}


def compile_stats(rows, dataset):
    out = {}
    for arm in sorted({r["arm"] for r in rows}):
        rs = [r for r in rows if r["arm"] == arm and r["dataset"] == dataset and not r.get("outage")]
        compiled = [r for r in rs if r["compiled"]]
        out[arm] = {
            "outputs": len(rs),
            "compile_rate": 100 * len(compiled) / len(rs) if rs else None,
            "faithful_given_compiled": 100 * sum(truth_value(r) for r in compiled) / len(compiled) if compiled else None,
            "format_failure_rate": 100 * sum(r["format_failure"] for r in rs) / len(rs) if rs else None,
            "memorization_rate": 100 * sum(bool(r["memorized"]) for r in rs) / len(rs) if rs else None,
            "cert_judge_disagreements": sum(1 for r in compiled if r["certified"] and r["ref_verdict"] != "faithful"),
            "outages": sum(1 for r in rows if r["arm"] == arm and r["dataset"] == dataset and r.get("outage")),
        }
    return out


def error_tags(rows, dataset):
    out = {}
    for arm in sorted({r["arm"] for r in rows}):
        tags = Counter(r["ref_error_tag"] for r in rows if r["arm"] == arm and r["dataset"] == dataset
                       and r["compiled"] and r["truth_label"] == "unfaithful" and r["ref_error_tag"])
        total = sum(tags.values())
        out[arm] = {t: {"count": c, "share": 100 * c / total} for t, c in tags.most_common()}
    return out


def read_labels(labels_path, sample_path):
    """Hand labels joined to the hidden sample mapping.

    sample.jsonl has one line per labeled output: {label_id, arm, item_id, gepa_seed, sample, parts},
    where `parts` lists "random" and/or "disagreement" (prereg Changes, item 13). The random part is one
    set of test items labeled in all four core arms, one GEPA seed per item for B and D. An output
    picked by both parts is shown once and counts in both.
    Returns [{label_id, label, arm, item_id, gepa_seed, sample, parts}].
    """
    with open(labels_path) as f:
        labels = {r["label_id"]: r["label"] for r in csv.DictReader(f)}
    with open(sample_path) as f:
        sample = [json.loads(line) for line in f if line.strip()]
    return [{**s, "label": labels.get(s["label_id"], "")} for s in sample]


def hand_check(rows, labeled, resamples, seed):
    """Reference judge agreement (random part) and Q1-Q3 on the random part, paired over its items."""
    key = {(r["arm"], r["item_id"], r["gepa_seed"], r["sample"]): r for r in rows if r["dataset"] == "test"}
    random_part = [x for x in labeled if "random" in x["parts"] and x["label"] in ("faithful", "unfaithful")]
    joined = [(x, key[(x["arm"], x["item_id"], x.get("gepa_seed"), x.get("sample", 0))]) for x in random_part]
    agree = defaultdict(lambda: [0, 0])
    for x, r in joined:
        if r["ref_verdict"] in ("faithful", "unfaithful"):
            for k in ("all", x["arm"]):
                agree[k][0] += r["ref_verdict"] == x["label"]
                agree[k][1] += 1
    agreement = {k: {"agree": a, "n": n, "rate": 100 * a / n} for k, (a, n) in sorted(agree.items())}

    # Paired: keep the random items labeled faithful or unfaithful in every core arm, then reuse the
    # test-split bootstrap on one-row matrices (truth = the hand label, judge = that output's judge score).
    by_item = defaultdict(dict)
    for x, r in joined:
        if x["arm"] in CORE:
            by_item[x["item_id"]][x["arm"]] = (100.0 * (x["label"] == "faithful"), 100.0 * judge_value(r))
    random_items = {x["item_id"] for x in labeled if "random" in x["parts"]}
    items = sorted(i for i, arms in by_item.items() if set(arms) == set(CORE))
    contrasts = {}
    if items:
        mats = {a: {"truth": np.array([[by_item[i][a][0] for i in items]]),
                    "judge": np.array([[by_item[i][a][1] for i in items]])} for a in CORE}
        contrasts, _ = bootstrap(mats, CONTRASTS, resamples, seed)
    unsure = sum(1 for x in labeled if x["label"] == "unsure")
    return {"judge_agreement_random_part": agreement, "contrasts_random_part_hand_labels": contrasts,
            "random_items": len(random_items), "random_items_paired": len(items),
            "items_dropped": len(random_items) - len(items),
            "labeled": len(labeled), "unsure": unsure,
            "disagreement_part": sum(1 for x in labeled if "disagreement" in x["parts"])}


def analyze(rows, cfg, labeled=None):
    a = cfg["analysis"]
    T, R, seed = a["threshold_points"], a["bootstrap_resamples"], a["seed"]
    results = {"threshold_points": T, "bootstrap_resamples": R}

    mats, items = matrices(rows, "test")
    contrasts, per_arm = bootstrap(mats, CONTRASTS, R, seed)
    for c in contrasts.values():
        c["decision"] = decide(c["estimate"], c["ci"], T)
    results["confirmatory"] = {"items": len(items), "arm_truth_rates": per_seed_rates(mats),
                               "per_arm_intervals": per_arm, "contrasts": contrasts}

    memorized = {r["item_id"] for r in rows if r["dataset"] == "test" and r["memorized"] and r["arm"] in CORE}
    m2, items2 = matrices(rows, "test", exclude=memorized)
    without, _ = bootstrap(m2, CONTRASTS, R, seed) if items2 else ({}, None)
    results["alongside"] = {
        "compile_and_memorization": compile_stats(rows, "test"),
        "contrasts_without_exact_matches": {"items_dropped": len(memorized), **without},
        "hand_check": hand_check(rows, labeled, R, seed) if labeled else "not available (no labels yet)",
    }

    explo = {"note": "exploratory"}
    if any(r["dataset"] == "minif2f" for r in rows):
        mm, mitems = matrices(rows, "minif2f")
        mc, mper = bootstrap(mm, EXPLORATORY_CONTRASTS, R, seed)
        explo["minif2f_transfer"] = {"items": len(mitems), "contrasts": mc, "per_arm_intervals": mper}
    explo["format_breakage"] = {arm: s["format_failure_rate"] for arm, s in compile_stats(rows, "test").items()}
    explo["error_tags"] = error_tags(rows, "test")
    results["exploratory"] = explo
    return results


def figures(results, out_dir):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    out_dir.mkdir(parents=True, exist_ok=True)
    per = results["confirmatory"]["per_arm_intervals"]
    arms = sorted({k.split(":")[0] for k in per})
    est = [per[f"{a}:truth"]["estimate"] for a in arms]
    err = [[e - per[f"{a}:truth"]["ci"][0] for a, e in zip(arms, est)], [per[f"{a}:truth"]["ci"][1] - e for a, e in zip(arms, est)]]
    fig, ax = plt.subplots(figsize=(6, 4))
    ax.bar(arms, est, yerr=err, capsize=4, color="#4a6fa5")
    ax.set_ylabel("Truth-scored faithful rate (points)")
    ax.set_title("Truth score by arm (95% bootstrap intervals)")
    fig.tight_layout()
    fig.savefig(out_dir / "truth_by_arm.png", dpi=150)
    plt.close(fig)

    c = results["confirmatory"]["contrasts"]
    gains = {}
    for model, (after, before) in {"Qwen3-8B": ("B", "A"), "ReForm-8B": ("D", "C")}.items():
        for score in ("judge", "truth"):
            gains[(model, score)] = per[f"{after}:{score}"]["estimate"] - per[f"{before}:{score}"]["estimate"]
    fig, ax = plt.subplots(figsize=(6, 4))
    x = np.arange(2)
    for k, (score, color) in enumerate((("judge", "#c0504d"), ("truth", "#4a6fa5"))):
        ax.bar(x + (k - 0.5) * 0.35, [gains[(m, score)] for m in ("Qwen3-8B", "ReForm-8B")], 0.35, label=f"{score} gain", color=color)
    for i, name in enumerate(("Q3_qwen3-8b", "Q3_reform-8b")):
        if name in c:
            ax.annotate(f"gap {c[name]['estimate']:.1f} [{c[name]['ci'][0]:.1f}, {c[name]['ci'][1]:.1f}]",
                        (x[i], max(gains[(m, s)] for m in ("Qwen3-8B", "ReForm-8B") for s in ("judge", "truth"))),
                        ha="center", va="bottom", fontsize=8)
    ax.axhline(0, color="#888", linewidth=0.8)
    ax.set_xticks(x, ["Qwen3-8B (A to B)", "ReForm-8B (C to D)"])
    ax.set_ylabel("GEPA gain (points)")
    ax.set_title("Judge gain vs truth gain")
    ax.legend()
    fig.tight_layout()
    fig.savefig(out_dir / "judge_vs_truth_gain.png", dpi=150)
    plt.close(fig)
