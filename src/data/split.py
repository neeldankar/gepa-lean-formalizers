"""Seeded train/val/test split, stratified by textbook."""
import random
from collections import defaultdict


def largest_remainder(counts, total):
    """Split `total` across groups in proportion to `counts`, summing exactly to `total`.

    Ties in the remainder go to the alphabetically first group.
    """
    n = sum(counts.values())
    exact = {k: c * total / n for k, c in counts.items()}
    quota = {k: int(v) for k, v in exact.items()}
    by_remainder = sorted(counts, key=lambda k: (-(exact[k] - quota[k]), k))
    for k in by_remainder[: total - sum(quota.values())]:
        quota[k] += 1
    return quota


def make_split(items, seed, sizes):
    """Return ({"train": [...], "val": [...], "test": [...]}, groups of ids kept together).

    Items sharing a `name` (the same problem listed twice) are kept in one split by swapping
    the stray copy with a random same-textbook item, so counts and strata don't change.
    """
    by_tb = defaultdict(list)
    for it in items:
        by_tb[it["textbook"]].append(it["id"])
    counts = {tb: len(ids) for tb, ids in by_tb.items()}
    if sum(counts.values()) != sizes["train"] + sizes["val"] + sizes["test"]:
        raise ValueError("split sizes don't add up to the item count")
    q_train = largest_remainder(counts, sizes["train"])
    q_val = largest_remainder(counts, sizes["val"])

    rng = random.Random(seed)
    split_of = {}
    for tb in sorted(by_tb):
        ids = sorted(by_tb[tb])
        rng.shuffle(ids)
        for i, id_ in enumerate(ids):
            split_of[id_] = "train" if i < q_train[tb] else "val" if i < q_train[tb] + q_val[tb] else "test"

    textbook = {it["id"]: it["textbook"] for it in items}
    by_name = defaultdict(list)
    for it in items:
        by_name[it["name"]].append(it["id"])
    groups = [sorted(ids) for _, ids in sorted(by_name.items()) if len(ids) > 1]
    grouped = {id_ for g in groups for id_ in g}
    for group in groups:
        target = split_of[group[0]]
        for id_ in group[1:]:
            if split_of[id_] == target:
                continue
            candidates = sorted(
                x for x in split_of
                if split_of[x] == target and textbook[x] == textbook[id_] and x not in grouped
            )
            swap = rng.choice(candidates)
            split_of[swap], split_of[id_] = split_of[id_], target

    return {name: sorted(i for i, s in split_of.items() if s == name) for name in ("train", "val", "test")}, groups


def per_textbook_counts(items, split):
    split_of = {id_: name for name, ids in split.items() for id_ in ids}
    table = defaultdict(lambda: {"total": 0, "train": 0, "val": 0, "test": 0})
    for it in items:
        row = table[it["textbook"]]
        row["total"] += 1
        row[split_of[it["id"]]] += 1
    return dict(sorted(table.items()))
