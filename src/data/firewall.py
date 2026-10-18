"""The only way code gets items.

GEPA code calls `gepa_items` and can only ever see train and validation. Test and miniF2F come
from `heldout_items`, which refuses to load until every GEPA run in config.yaml has finished
(a DONE marker in runs/<run_id>/), so nothing about them can reach optimization.
"""
import json

from src.config import ROOT
from src.data.proofnet import read_jsonl

GEPA_SPLITS = ("train", "val")


class FirewallError(RuntimeError):
    pass


def _splits(root):
    return json.loads((root / "data/splits.json").read_text())


def gepa_items(split, root=ROOT):
    if split not in GEPA_SPLITS:
        raise FirewallError(f"GEPA code may not load {split!r}")
    ids = set(_splits(root)[split])
    return [it for it in read_jsonl(root / "data/proofnet_verified.jsonl") if it["id"] in ids]


def check_gepa_batch(items, root=ROOT):
    """Raise if any item is not train or validation (called on every GEPA evaluation)."""
    s = _splits(root)
    allowed = set(s["train"]) | set(s["val"])
    bad = [it["id"] for it in items if it["id"] not in allowed]
    if bad:
        raise FirewallError(f"GEPA got non-train/val items: {bad[:5]}")


def unfinished_gepa_runs(cfg, runs_dir=ROOT / "runs"):
    return [run_id for run_id in cfg["gepa"]["runs"] if not (runs_dir / run_id / "DONE").exists()]


def heldout_items(name, cfg, root=ROOT, runs_dir=None):
    """`test` (247 ProofNet-Verified items) or `minif2f`. Locked until all GEPA runs are done."""
    unfinished = unfinished_gepa_runs(cfg, runs_dir or root / "runs")
    if unfinished:
        raise FirewallError(f"held-out data is locked until these GEPA runs finish: {unfinished}")
    if name == "test":
        ids = set(_splits(root)["test"])
        return [it for it in read_jsonl(root / "data/proofnet_verified.jsonl") if it["id"] in ids]
    if name == "minif2f":
        return read_jsonl(root / "data/minif2f.jsonl")
    raise ValueError(name)
