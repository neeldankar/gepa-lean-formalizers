"""Memorization check: exact matches against known ProofNet statements after normalizing.

Normalizing = AXLE `normalize` (doc comments to plain comments, its default normalizations),
then no comments, fixed theorem name, `:= by sorry`, and all whitespace removed (so `x*y` and
`x * y` match). Sources are Lean 4 only, all from ProofNet-Verified's repo at the pinned commit:
ProofNet-Verified, ProofNet#, and two Lean 4 ports of the original ProofNet. The original
ProofNet is Lean 3 only and is skipped.
"""
import json
import re
import urllib.parse
import urllib.request

from src.config import ROOT
from src.data.proofnet import read_jsonl
from src.scoring.normalize import normalize_statement

NORMALIZATIONS = ["remove_sections", "remove_duplicates", "split_open_in_commands", "normalize_doc_comments"]
RAW_URL = "https://raw.githubusercontent.com/{repo}/{commit}/{path}"
SKIPPED = {"ProofNet (original)": "Lean 3 only"}
# name -> (path in the ProofNet-Verified repo, header field, statement field)
SOURCES = {
    "ProofNet-Verified": ("data/proofnet-verified.jsonl", "header", "formal_stmt"),
    "ProofNet#": ("data/proofnet#/proofnet#.jsonl", "lean4_src_header", "lean4_formalization"),
    "ProofNet-lean4 (6deae98)": ("data/proofnet/proofnet_lean4-6deae98.jsonl", "header", "formal_statement"),
    "ProofNet (Lean 4.28 port)": ("data/proofnet/proofnet-4.28.jsonl", "header", "formal_stmt"),
}
INDEX_PATH = ROOT / "data/memorization_index.json"


def raw_path(path):
    return ROOT / "data/raw/memorization" / path.replace("/", "__")


def download_sources(cfg):
    for path, _, _ in SOURCES.values():
        dest = raw_path(path)
        if not dest.exists():
            dest.parent.mkdir(parents=True, exist_ok=True)
            url = RAW_URL.format(repo=cfg["repo"], commit=cfg["commit"], path=urllib.parse.quote(path))
            with urllib.request.urlopen(url) as resp:
                dest.write_bytes(resp.read())


def theorem_part(content):
    """From the first `theorem`/`lemma` keyword at a line start to the end."""
    m = re.search(r"^(?:theorem|lemma)\b", content, re.MULTILINE)
    return content[m.start():] if m else None


def keys_for(checker, headers, statements):
    """Normalized match key per statement (None if it can't be normalized)."""
    contents = []
    for header, stmt in zip(headers, statements):
        stmt = stmt.rstrip()
        if stmt.endswith(":="):
            stmt += " by\n  sorry"
        contents.append(f"{header.strip()}\n\n{stmt}")
    results = checker.normalize_many(contents, NORMALIZATIONS, progress_every=200)
    keys = []
    for content, result in zip(contents, results):
        text = theorem_part(result.content if result.content else content)
        norm = normalize_statement(text) if text else None
        keys.append("".join(norm.split()) if norm else None)
    return keys


def build_index(checker, cfg):
    """{key: [source names]} plus per-source counts. Saved to data/memorization_index.json."""
    download_sources(cfg)
    index, counts = {}, {}
    for name, (path, header_field, stmt_field) in SOURCES.items():
        rows = read_jsonl(raw_path(path))
        keys = keys_for(checker, [r[header_field] for r in rows], [r[stmt_field] for r in rows])
        counts[name] = {"rows": len(rows), "keys": sum(k is not None for k in keys)}
        for k in keys:
            if k and name not in index.setdefault(k, []):
                index[k].append(name)
    INDEX_PATH.write_text(json.dumps({"skipped": SKIPPED, "counts": counts, "index": index}, ensure_ascii=False) + "\n")
    return index, counts


def load_index():
    return json.loads(INDEX_PATH.read_text())["index"]


def exact_matches(checker, index, items, statements):
    """Source names matched by each candidate statement ([] if none)."""
    keys = keys_for(checker, [it["header"] for it in items], statements)
    return [index.get(k, []) if k else [] for k in keys]

