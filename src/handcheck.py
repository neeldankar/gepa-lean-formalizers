"""Chunk 6 hand-check sample (prereg: Neel's hand-check, Changes item 13; Deviation 5).

Two parts, test outputs from the four core arms only:
- disagreement: every output with an equivalence certificate that the reference judge calls unfaithful
  (up to `cap`, drawn at random if there are more)
- random: test items drawn at random, each in all four core arms; for B and D one GEPA seed is drawn per
  item. Items are added until about `target` outputs are on the page.

Deviation 5 (Neel, 2026-10-23): only compiled outputs go on the page. A random-part output that did not
compile is left off and gets `fixed_label: "unfaithful"` (the frozen compile rule), so its item stays
paired across the four arms. An output picked by both parts is shown once and lists both.
"""
import random

CORE = ("A", "B", "C", "D")
GEPA_ARMS = ("B", "D")


def key(row):
    return row["arm"], row["item_id"], row["gepa_seed"], row["sample"]


def build_sample(rows, seed, target=100, cap=25):
    """[{label_id, arm, run_id, item_id, gepa_seed, sample, parts, shown, fixed_label?}] with the shown
    entries first in shuffled page order, then the fixed-label entries."""
    rng = random.Random(seed)
    test = [r for r in rows if r["dataset"] == "test" and r["arm"] in CORE and r["sample"] == 0]
    by_key = {key(r): r for r in test}
    picked = {}

    dis = sorted((r for r in test if r["compiled"] and r["certified"] and r["ref_verdict"] == "unfaithful"), key=key)
    if len(dis) > cap:
        dis = sorted(rng.sample(dis, cap), key=key)
    for r in dis:
        picked[key(r)] = {"row": r, "parts": ["disagreement"]}

    seeds = {arm: sorted({r["gepa_seed"] for r in test if r["arm"] == arm}) for arm in GEPA_ARMS}
    items = sorted({r["item_id"] for r in test})
    rng.shuffle(items)
    shown = len(picked)
    for item in items:
        if shown >= target:
            break
        for arm in CORE:
            r = by_key[(arm, item, rng.choice(seeds[arm]) if arm in GEPA_ARMS else None, 0)]
            entry = picked.setdefault(key(r), {"row": r, "parts": []})
            if not entry["parts"] and r["compiled"]:
                shown += 1
            entry["parts"].append("random")

    entries = list(picked.values())
    rng.shuffle(entries)
    ids = set()
    out = []
    for e in entries:
        label_id = f"{rng.getrandbits(32):08x}"
        while label_id in ids:
            label_id = f"{rng.getrandbits(32):08x}"
        ids.add(label_id)
        r = e["row"]
        s = {"label_id": label_id, "arm": r["arm"], "run_id": r["run_id"], "item_id": r["item_id"],
             "gepa_seed": r["gepa_seed"], "sample": r["sample"], "parts": e["parts"], "shown": bool(r["compiled"])}
        if not r["compiled"]:
            s["fixed_label"] = "unfaithful"
        out.append(s)
    return [s for s in out if s["shown"]] + [s for s in out if not s["shown"]]


def summary(sample):
    """Pooled counts only: nothing per arm, no verdicts."""
    rand = [s for s in sample if "random" in s["parts"]]
    return {"entries": len(sample), "shown": sum(s["shown"] for s in sample),
            "fixed_label_not_shown": sum(not s["shown"] for s in sample),
            "disagreement_part": sum("disagreement" in s["parts"] for s in sample),
            "random_items": len({s["item_id"] for s in rand}), "random_outputs": len(rand),
            "in_both_parts": sum(len(s["parts"]) == 2 for s in sample)}


def page_records(sample, rows, items, normalize):
    """Records for labeling.build_page, in page order: the shown entries only, English/reference/candidate."""
    by_key = {key(r): r for r in rows}
    return [{"label_id": s["label_id"], "english": items[s["item_id"]]["informal_stmt"],
             "reference": normalize(items[s["item_id"]]["formal_stmt"]),
             "candidate": by_key[(s["arm"], s["item_id"], s["gepa_seed"], s["sample"])]["normalized"]}
            for s in sample if s["shown"]]


LABELS = ("faithful", "unfaithful", "unsure")


def validate_labels(labels_path, sample_path):
    """labels.csv against the sample: header, one row per shown output, no strays, no blanks. Pooled counts only."""
    import csv
    import json
    from collections import Counter
    with open(labels_path, newline="") as f:
        reader = csv.reader(f)
        header = next(reader, [])
        rows = [r for r in reader if r]
    with open(sample_path) as f:
        shown = {s["label_id"] for s in map(json.loads, filter(str.strip, f)) if s["shown"]}
    ids = [r[0] for r in rows]
    checks = {"header_ok": header == ["label_id", "label"], "rows": len(rows), "rows_ok": len(rows) == len(shown),
              "no_duplicates": len(set(ids)) == len(ids), "missing_ids": len(shown - set(ids)),
              "stray_ids": len(set(ids) - shown), "bad_or_blank_labels": sum(len(r) != 2 or r[1] not in LABELS for r in rows)}
    checks["ok"] = (checks["header_ok"] and checks["rows_ok"] and checks["no_duplicates"]
                    and not checks["missing_ids"] and not checks["stray_ids"] and not checks["bad_or_blank_labels"])
    checks["label_counts"] = dict(sorted(Counter(r[1] for r in rows if len(r) == 2).items()))
    return checks


def headline(results):
    """results.json in the shape the chunk 6 subagent writes, so the two can be compared key by key."""
    conf, along = results["confirmatory"], results["alongside"]
    stats, hc = along["compile_and_memorization"], along["hand_check"]
    ests = lambda d: {k: {"estimate": v["estimate"], "ci": v["ci"]} for k, v in d.items()}
    return {
        "per_arm": {arm: {**{s: conf["per_arm_intervals"][f"{arm}:{s}"] for s in ("truth", "judge", "fpr")},
                          **{k: stats[arm][k] for k in ("outputs", "compile_rate", "faithful_given_compiled")}}
                    for arm in sorted(stats)},
        "contrasts": conf["contrasts"],
        "descriptive": conf["descriptive"],
        "truth_gain_split": {k: v for k, v in along["truth_gain_split"].items() if k != "note"},
        "without_exact_matches": {"items_dropped": along["contrasts_without_exact_matches"]["items_dropped"],
                                  **ests({k: v for k, v in along["contrasts_without_exact_matches"].items() if k != "items_dropped"})},
        "hand_check": {"agreement": {k: {"agree": v["agree"], "n": v["n"]} for k, v in hc["judge_agreement_random_part"].items()},
                       "errors": {k: {x: v[x] for x in ("false_positive", "false_negative", "n")} for k, v in hc["judge_errors_random_part"].items()},
                       "random_part_contrasts": ests(hc["contrasts_random_part_hand_labels"]),
                       **{k: hc[k] for k in ("random_items", "random_items_paired", "unsure", "disagreement_part")}},
    }


def compare(ours, theirs, ci_tol=0.5, eps=1e-6):
    """Every leaf in `ours`: estimates and counts must match exactly (to float noise), CI ends within ci_tol points."""
    rows = []

    def walk(a, b, path):
        if isinstance(a, dict):
            for k in a:
                walk(a[k], b.get(k) if isinstance(b, dict) else None, path + [k])
            return
        name = ".".join(path)
        if path[-1] == "ci":
            ok = isinstance(b, list) and len(b) == 2 and all(abs(x - y) <= ci_tol for x, y in zip(a, b))
        elif isinstance(a, str):
            ok = a == b
        else:
            ok = isinstance(b, (int, float)) and abs(a - b) <= eps
        rows.append({"key": name, "ours": a, "theirs": b, "ok": ok})

    walk(ours, theirs, [])
    return {"ok": all(r["ok"] for r in rows), "checked": len(rows), "mismatches": [r for r in rows if not r["ok"]], "rows": rows}
