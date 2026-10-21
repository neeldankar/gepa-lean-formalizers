"""Chunk 6 analysis, written in chunk 3 before any results exist (prereg Analysis plan).

All rates are in points (0 to 100). A per-item value is the mean over samples. For GEPA arms
(several seeds), the arm's value is the mean over seeds. The paired bootstrap resamples test items
(the same draw for every arm) and, within each GEPA arm, resamples its seeds with replacement.

Confirmatory, on the test split:
  Q1 = B - A (truth)
  Q2 = (D - C) - (B - A) (truth)
  Q3 = judge false-positive rate among compiled outputs (judge faithful, truth unfaithful, divided by
       compiled), GEPA arm minus seed arm, for Qwen3-8B (B - A) and ReForm-8B (D - C). Per GEPA seed
       the rate is a ratio of sums over items; the arm's rate is the mean over seeds.
Descriptive (no decision rule): judge-score gain minus truth-score gain, per model.
Reported alongside (prereg draft, chunk 4): the source of each truth label per arm; the reference judge's
false positives and false negatives against the hand labels; and each truth gain split into a compile
part and a meaning part, dT = f0 * dc + c1 * df (c = compile rate, f = faithful given compiled, both
pooled over seeds and items so the split is exact), with paired-bootstrap intervals.
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
    "Q3_qwen3-8b": {"fpr": {"B": 1, "A": -1}},
    "Q3_reform-8b": {"fpr": {"D": 1, "C": -1}},
}
DESCRIPTIVE_CONTRASTS = {
    "judge_gain_minus_truth_gain_qwen3-8b": {"judge": {"B": 1, "A": -1}, "truth": {"B": -1, "A": 1}},
    "judge_gain_minus_truth_gain_reform-8b": {"judge": {"D": 1, "C": -1}, "truth": {"D": -1, "C": 1}},
}
SCORES = ("truth", "judge", "fpr")
# Truth-gain splits: Q1 is A to B; Q2's two terms are C to D and A to B.
DECOMPOSITIONS = {"A_to_B": ("A", "B"), "C_to_D": ("C", "D")}
EXPLORATORY_CONTRASTS = {k: CONTRASTS[k] for k in ("Q1", "Q2")}


def truth_value(row):
    return 1.0 if row["truth_label"] == "faithful" else 0.0


def judge_value(row):
    return float(row["judge_score"] or 0)


def false_positive(row):
    """Compiled, the optimization judge says faithful, the truth label says unfaithful."""
    return 1.0 if row["compiled"] and judge_value(row) == 1 and row["truth_label"] != "faithful" else 0.0


def matrices(rows, dataset, items=None, exclude=frozenset()):
    """{arm: {"truth"/"judge"/"fp"/"compiled": array (seeds x items)}} over a shared item order."""
    rows = [r for r in rows if r["dataset"] == dataset and not r.get("outage")]
    item_ids = sorted(items if items is not None else {r["item_id"] for r in rows} - set(exclude))
    pos = {i: k for k, i in enumerate(item_ids)}
    acc = defaultdict(lambda: defaultdict(list))
    for r in rows:
        if r["item_id"] in pos:
            acc[(r["arm"], r["gepa_seed"])][r["item_id"]].append(r)
    values = {"truth": truth_value, "judge": judge_value, "fp": false_positive, "compiled": lambda r: float(r["compiled"])}
    out = defaultdict(lambda: {k: [] for k in values})
    for (arm, seed), by_item in sorted(acc.items(), key=lambda kv: (kv[0][0], -1 if kv[0][1] is None else kv[0][1])):
        for k, f in values.items():
            v = np.full(len(item_ids), np.nan)
            for i, rs in by_item.items():
                v[pos[i]] = np.mean([f(r) for r in rs])
            out[arm][k].append(v)
    return {arm: {k: np.array(v) * 100 for k, v in d.items()} for arm, d in out.items()}, item_ids


def arm_means(mats, idx=None, seed_draws=None):
    """{(arm, score): mean} for truth, judge and fpr, optionally on resampled items and seeds."""
    out = {}
    for arm, d in mats.items():
        seeds = seed_draws[arm] if seed_draws else np.arange(d["truth"].shape[0])
        pick = (lambda m: m[seeds]) if idx is None else (lambda m: m[np.ix_(seeds, idx)])
        for score in ("truth", "judge"):
            out[(arm, score)] = float(np.nanmean(pick(d[score])))
        if "fp" in d:
            fp, comp = np.nansum(pick(d["fp"]), axis=1), np.nansum(pick(d["compiled"]), axis=1)
            with np.errstate(invalid="ignore", divide="ignore"):
                per_seed = np.where(comp > 0, 100 * fp / comp, np.nan)
            out[(arm, "fpr")] = float(np.nanmean(per_seed)) if np.isfinite(per_seed).any() else float("nan")
        if "compiled" in d:  # pooled over the drawn seeds and items, so truth = c * f / 100 exactly
            comp, tr = pick(d["compiled"]), pick(d["truth"])
            out[(arm, "c")] = float(np.nanmean(comp))
            total = np.nansum(comp)
            out[(arm, "f")] = float(100 * np.nansum(tr) / total) if total > 0 else float("nan")
    return out


def decomposition(means, before, after):
    """dT = f0 * dc + c1 * df, in points."""
    c0, f0, c1, f1 = means[(before, "c")], means[(before, "f")], means[(after, "c")], means[(after, "f")]
    return {"compile_part": f0 * (c1 - c0) / 100, "meaning_part": c1 * (f1 - f0) / 100,
            "total": means[(after, "truth")] - means[(before, "truth")]}


def decomposition_fns(mats):
    fns = {}
    for name, (b, a) in DECOMPOSITIONS.items():
        if b in mats and a in mats:
            for part in ("compile_part", "meaning_part", "total"):
                fns[f"{name}:{part}"] = lambda m, b=b, a=a, part=part: decomposition(m, b, a)[part]
    return fns


def contrast_value(means, spec):
    return sum(w * means[(arm, score)] for score, arms in spec.items() for arm, w in arms.items())


def bootstrap(mats, contrasts, resamples, seed, derived=None):
    """{name: {"estimate", "ci": [lo, hi]}} plus per-arm means with intervals. `derived` maps extra names
    to functions of the arm means (computed on the same resamples)."""
    derived = derived or {}
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
        for name, fn in derived.items():
            draws[name].append(fn(means))
        for key, v in means.items():
            arm_draws[key].append(v)
    result = {}
    for name, fn in derived.items():
        lo, hi = np.nanpercentile(draws[name], [2.5, 97.5])
        result[name] = {"estimate": fn(point), "ci": [float(lo), float(hi)]}
    for name, spec in contrasts.items():
        if name in draws:
            lo, hi = np.nanpercentile(draws[name], [2.5, 97.5])
            result[name] = {"estimate": contrast_value(point, spec), "ci": [float(lo), float(hi)]}
    per_arm = {f"{arm}:{score}": {"estimate": point[(arm, score)], "ci": [float(x) for x in np.nanpercentile(v, [2.5, 97.5])]}
               for (arm, score), v in arm_draws.items() if score in SCORES}
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
            "truth_source_share": truth_sources(rs),
        }
    return out


def truth_sources(rs):
    """Share (points) of truth labels from a certificate, the reference judge, or a compile failure
    (format failures included there, and also shown on their own)."""
    if not rs:
        return None
    n = len(rs)
    src = Counter(r["truth_source"] for r in rs)
    return {"certificate": 100 * src["certificate"] / n, "ref_judge": 100 * src["ref_judge"] / n,
            "compile_failure": 100 * (src["compile"] + src["format"]) / n, "of_which_format": 100 * src["format"] / n}


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
    errors = defaultdict(lambda: {"false_positive": 0, "false_negative": 0, "n": 0})
    for x, r in joined:
        if r["ref_verdict"] in ("faithful", "unfaithful"):
            for k in ("all", x["arm"]):
                errors[k]["n"] += 1
                errors[k]["false_positive"] += r["ref_verdict"] == "faithful" and x["label"] == "unfaithful"
                errors[k]["false_negative"] += r["ref_verdict"] == "unfaithful" and x["label"] == "faithful"
    judge_errors = {k: {**e, "false_positive_rate": 100 * e["false_positive"] / e["n"],
                        "false_negative_rate": 100 * e["false_negative"] / e["n"]} for k, e in sorted(errors.items())}

    # Paired: keep the random items labeled faithful or unfaithful in every core arm, then reuse the
    # test-split bootstrap on one-row matrices (truth = the hand label, judge = that output's judge score,
    # a false positive = judge score 1 and hand label unfaithful).
    by_item = defaultdict(dict)
    for x, r in joined:
        if x["arm"] in CORE:
            by_item[x["item_id"]][x["arm"]] = (100.0 * (x["label"] == "faithful"), 100.0 * judge_value(r),
                                               100.0 * (judge_value(r) == 1 and x["label"] == "unfaithful"),
                                               100.0 * bool(r["compiled"]))
    random_items = {x["item_id"] for x in labeled if "random" in x["parts"]}
    items = sorted(i for i, arms in by_item.items() if set(arms) == set(CORE))
    contrasts = {}
    if items:
        mats = {a: {k: np.array([[by_item[i][a][n] for i in items]]) for n, k in enumerate(("truth", "judge", "fp", "compiled"))}
                for a in CORE}
        contrasts, _ = bootstrap(mats, CONTRASTS, resamples, seed)
    unsure = sum(1 for x in labeled if x["label"] == "unsure")
    return {"judge_agreement_random_part": agreement, "judge_errors_random_part": judge_errors,
            "contrasts_random_part_hand_labels": contrasts,
            "random_items": len(random_items), "random_items_paired": len(items),
            "items_dropped": len(random_items) - len(items),
            "labeled": len(labeled), "unsure": unsure,
            "disagreement_part": sum(1 for x in labeled if "disagreement" in x["parts"])}


def analyze(rows, cfg, labeled=None):
    a = cfg["analysis"]
    T, R, seed = a["threshold_points"], a["bootstrap_resamples"], a["seed"]
    results = {"threshold_points": T, "bootstrap_resamples": R}

    mats, items = matrices(rows, "test")
    both, per_arm = bootstrap(mats, {**CONTRASTS, **DESCRIPTIVE_CONTRASTS}, R, seed, derived=decomposition_fns(mats))
    contrasts = {k: v for k, v in both.items() if k in CONTRASTS}
    split = defaultdict(dict)
    for k, v in both.items():
        if ":" in k:
            name, part = k.split(":")
            split[name][part] = v
    for c in contrasts.values():
        c["decision"] = decide(c["estimate"], c["ci"], T)
    results["confirmatory"] = {"items": len(items), "arm_truth_rates": per_seed_rates(mats),
                               "per_arm_intervals": per_arm, "contrasts": contrasts,
                               "descriptive": {k: v for k, v in both.items() if k in DESCRIPTIVE_CONTRASTS}}

    memorized = {r["item_id"] for r in rows if r["dataset"] == "test" and r["memorized"] and r["arm"] in CORE}
    m2, items2 = matrices(rows, "test", exclude=memorized)
    without, _ = bootstrap(m2, CONTRASTS, R, seed) if items2 else ({}, None)
    results["alongside"] = {
        "compile_and_memorization": compile_stats(rows, "test"),
        "truth_gain_split": {"note": "A_to_B is Q1 and Q2's Qwen3-8B term; C_to_D is Q2's ReForm-8B term", **split},
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

    c = results["confirmatory"]["descriptive"]
    gains = {}
    for model, (after, before) in {"Qwen3-8B": ("B", "A"), "ReForm-8B": ("D", "C")}.items():
        for score in ("judge", "truth"):
            gains[(model, score)] = per[f"{after}:{score}"]["estimate"] - per[f"{before}:{score}"]["estimate"]
    fig, ax = plt.subplots(figsize=(6, 4))
    x = np.arange(2)
    for k, (score, color) in enumerate((("judge", "#c0504d"), ("truth", "#4a6fa5"))):
        ax.bar(x + (k - 0.5) * 0.35, [gains[(m, score)] for m in ("Qwen3-8B", "ReForm-8B")], 0.35, label=f"{score} gain", color=color)
    for i, name in enumerate(("judge_gain_minus_truth_gain_qwen3-8b", "judge_gain_minus_truth_gain_reform-8b")):
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
