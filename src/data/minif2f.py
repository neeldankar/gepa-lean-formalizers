"""miniF2F (AI-MO version): download at a pinned revision and map to our item format.

Each `formal_statement` is header + the English docstring (`informal_prefix`) + the theorem,
ending in `:= by`. We split it at the docstring and close the proof with `sorry`. The one
scripted edit is the big-operator binder rewrite below (prereg Changes, item 8). Items are
never hand-fixed; the ones that don't compile are dropped by scripts/chunk1.py.
"""
import re

from src.config import ROOT
from src.data.proofnet import read_jsonl, write_jsonl

RAW_PATH = ROOT / "data/raw/minif2f_test.jsonl"
ITEMS_PATH = ROOT / "data/minif2f.jsonl"


def download(cfg, path=RAW_PATH):
    if not path.exists():
        from datasets import load_dataset

        ds = load_dataset(cfg["repo"], split="train", revision=cfg["revision"])
        write_jsonl(path, list(ds))
    return path


# `∑ x in s` / `∏ x in s` (old Mathlib binder) -> `∑ x ∈ s`. Only a single identifier binder
# directly after the operator is touched.
BINDER_IN = re.compile(r"([∑∏]\s*)([^\W\d][\w'!?]*)\s+in\s+")


def rewrite_binders(stmt):
    return BINDER_IN.sub(r"\1\2 ∈ ", stmt)


def strip_docstring(prefix):
    s = prefix.strip()
    if not (s.startswith("/--") and s.endswith("-/")):
        raise ValueError(f"not a docstring: {prefix[:60]!r}")
    return s[3:-2].strip()


def to_item(row):
    prefix, full = row["informal_prefix"], row["formal_statement"]
    if full.count(prefix) != 1:
        raise ValueError(f"{row['name']}: docstring not found exactly once")
    header, stmt = full.split(prefix)
    rewritten = rewrite_binders(stmt)
    return {
        "id": f"minif2f_{row['name']}",
        "name": row["name"],
        "informal_stmt": strip_docstring(prefix),
        "header": header.strip(),
        "helper": "",
        "formal_stmt": rewritten.rstrip() + "\n  sorry",
        "binder_rewrite": rewritten != stmt,
    }


def load_raw_items(cfg):
    return [to_item(row) for row in read_jsonl(download(cfg))]


def save_usable(items):
    write_jsonl(ITEMS_PATH, items)
