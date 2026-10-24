"""Chunk 6: hand-check and analysis.

Usage: python -m scripts.chunk6 sample | validate | compare | examples

sample: builds the hand-check sample from runs/final/ (after Deviation 4) into runs/handcheck/:
sample.jsonl (the hidden mapping from label_id to arm and item; Neel does not open it), labeling.html
(the blind page, shown outputs only, each Lean statement glossed on its own) and sample_summary.json
(pooled counts only). Gloss calls are cached and charged to chunk 6.

validate: checks runs/handcheck/labels.csv against sample.jsonl into labels_check.json (pooled counts only).

compare: results.json against the subagent's runs/chunk6_subagent.json into runs/chunk6_compare.json.

examples: 5 random test outputs (seeded) with their scores into runs/chunk6_examples.json, for Neel to eyeball.
"""
import json
import random
import sys

from src.config import ROOT, load_config, load_env
from src.data.firewall import heldout_items
from src.final_eval import read_rows
from src.handcheck import build_sample, page_records, compare, headline, summary, validate_labels
from src.llm import LLMClient, spent
from src.scoring.labeling import build_page
from src.scoring.normalize import normalize_statement

OUT = ROOT / "runs/handcheck"
PAGE_KEY = "chunk6-handcheck"


def make_sample(cfg, out=OUT):
    rows = [r for arm in ("A", "B", "C", "D") for r in read_rows(ROOT / f"runs/final/{arm}.jsonl.gz")]
    sample = build_sample(rows, cfg["analysis"]["seed"])
    out.mkdir(parents=True, exist_ok=True)
    (out / "sample.jsonl").write_text("".join(json.dumps(s) + "\n" for s in sample))
    items = {it["id"]: it for it in heldout_items("test", cfg)}
    records = page_records(sample, rows, items, normalize_statement)
    before = spent(6)
    build_page(LLMClient(cfg, 6, run_id="handcheck_gloss"), cfg, records, out / "labeling.html", PAGE_KEY)
    result = {**summary(sample), "seed": cfg["analysis"]["seed"], "page_key": PAGE_KEY, "gloss_usd": spent(6) - before}
    (out / "sample_summary.json").write_text(json.dumps(result, indent=1) + "\n")
    return result


def main(argv):
    if argv[:1] == ["sample"]:
        load_env()
        print(json.dumps(make_sample(load_config()), indent=1))
        return
    if argv[:1] == ["validate"]:
        result = validate_labels(OUT / "labels.csv", OUT / "sample.jsonl")
        (OUT / "labels_check.json").write_text(json.dumps(result, indent=1) + "\n")
        print(json.dumps(result, indent=1))
        sys.exit(0 if result["ok"] else 1)
    if argv[:1] == ["compare"]:
        ours = headline(json.loads((ROOT / "results.json").read_text()))
        result = compare(ours, json.loads((ROOT / "runs/chunk6_subagent.json").read_text()))
        (ROOT / "runs/chunk6_compare.json").write_text(json.dumps(result, indent=1) + "\n")
        print(json.dumps({k: result[k] for k in ("ok", "checked", "mismatches")}, indent=1))
        sys.exit(0 if result["ok"] else 1)
    if argv[:1] == ["examples"]:
        cfg = load_config()
        rows = [r for p in sorted((ROOT / "runs/final").glob("*.jsonl.gz")) for r in read_rows(p) if r["dataset"] == "test"]
        items = {it["id"]: it for it in heldout_items("test", cfg)}
        picks = random.Random(cfg["analysis"]["seed"]).sample(rows, 5)
        out = [{"arm": r["arm"], "item_id": r["item_id"], "english": items[r["item_id"]]["informal_stmt"],
                "candidate": r["normalized"], **{k: r[k] for k in ("compiled", "judge_score", "certified", "ref_verdict", "truth_label")}}
               for r in picks]
        (ROOT / "runs/chunk6_examples.json").write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
        print(json.dumps(out, indent=1, ensure_ascii=False))
        return
    sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
