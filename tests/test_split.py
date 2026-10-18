import json

import pytest

from src.config import ROOT, load_config
from src.data.proofnet import ITEMS_PATH, read_jsonl
from src.data.split import largest_remainder, make_split, per_textbook_counts

CFG = load_config()
SIZES = CFG["split"]


@pytest.fixture(scope="module")
def items():
    return read_jsonl(ITEMS_PATH)


@pytest.fixture(scope="module")
def split(items):
    return make_split(items, CFG["seed"], SIZES)[0]


def test_sizes_exact(split):
    assert {k: len(v) for k, v in split.items()} == {"train": 50, "val": 70, "test": 247}


def test_no_id_in_two_splits_and_all_covered(items, split):
    all_ids = split["train"] + split["val"] + split["test"]
    assert len(all_ids) == len(set(all_ids)) == len(items)
    assert set(all_ids) == {it["id"] for it in items}


def test_same_seed_same_split(items, split):
    assert make_split(items, CFG["seed"], SIZES)[0] == split


def test_different_seed_different_split(items, split):
    assert make_split(items, CFG["seed"] + 1, SIZES)[0] != split


def test_saved_split_matches_seed(split):
    saved = json.loads((ROOT / "data/splits.json").read_text())
    assert saved["seed"] == CFG["seed"]
    assert {k: saved[k] for k in ("train", "val", "test")} == split


def test_every_textbook_in_every_split_in_proportion(items, split):
    n = len(items)
    for tb, row in per_textbook_counts(items, split).items():
        for name in ("train", "val", "test"):
            assert row[name] >= 1, (tb, name)
            expected = row["total"] * SIZES[name] / n
            assert abs(row[name] - expected) <= 1, (tb, name, row[name], expected)


def test_duplicate_problems_share_a_split(items, split):
    split_of = {i: name for name, ids in split.items() for i in ids}
    _, groups = make_split(items, CFG["seed"], SIZES)
    assert groups  # Rudin_exercise_4_8a is listed twice
    for group in groups:
        assert len({split_of[i] for i in group}) == 1


def test_largest_remainder_sums_exactly():
    quota = largest_remainder({"a": 5, "b": 3, "c": 2}, 7)
    assert sum(quota.values()) == 7
    assert quota == {"a": 4, "b": 2, "c": 1}
