"""ProofNet-Verified: download at a pinned commit and map to our item format."""
import json
import urllib.request
from pathlib import Path

from src.config import ROOT

RAW_URL = "https://raw.githubusercontent.com/{repo}/{commit}/data/proofnet-verified.jsonl"
RAW_PATH = ROOT / "data/raw/proofnet-verified.jsonl"
ITEMS_PATH = ROOT / "data/proofnet_verified.jsonl"


def download(cfg, path=RAW_PATH):
    """Fetch the raw jsonl once. Never edited after download."""
    path = Path(path)
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        url = RAW_URL.format(repo=cfg["repo"], commit=cfg["commit"])
        with urllib.request.urlopen(url) as resp:
            path.write_bytes(resp.read())
    return path


def to_item(row):
    # `name` is not unique (Rudin_exercise_4_8a appears twice), so the id comes from `index`.
    return {
        "id": f"pnv_{row['index']:03d}",
        "index": row["index"],
        "name": row["name"],
        "textbook": row["textbook"],
        "informal_stmt": row["informal_stmt"],
        "header": row["header"],
        "helper": row["helper"],
        "formal_stmt": row["formal_stmt"],
    }


def reference_content(item):
    """Header, helper definitions and the reference statement (already ending in `sorry`)."""
    return "\n\n".join(p for p in (item["header"], item["helper"], item["formal_stmt"]) if p.strip())


def read_jsonl(path):
    with open(path) as f:
        return [json.loads(line) for line in f if line.strip()]


def write_jsonl(path, rows):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def build_items(cfg):
    items = [to_item(row) for row in read_jsonl(download(cfg))]
    write_jsonl(ITEMS_PATH, items)
    return items
