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
