"""Chunk 1: load both datasets, compile every reference statement, make the split.

Writes data/proofnet_verified.jsonl, data/splits.json, data/minif2f.jsonl and
runs/chunk1/{proofnet_compile,minif2f_compile}.jsonl, runs/chunk1/summary.json.
Safe to rerun: AXLE results are cached, so only outages get retried.
`--report` prints the LOG.md tables from summary.json and 5 random raw examples instead.
"""
import json
import random
import sys
from collections import Counter

from src.axle_check import OK, OUTAGE, AxleChecker
from src.config import ROOT, load_config
from src.data import minif2f, proofnet
from src.data.split import make_split, per_textbook_counts

RUN_DIR = ROOT / "runs/chunk1"


def compile_all(checker, items, path):
    results = checker.check_many([proofnet.reference_content(it) for it in items], progress_every=50)
    rows = [{"id": it["id"], "status": r.status, "errors": r.errors} for it, r in zip(items, results)]
    proofnet.write_jsonl(path, rows)
    return rows


def compile_summary(rows):
    return {
        "total": len(rows),
        "compiled": sum(r["status"] == OK for r in rows),
        "by_status": dict(Counter(r["status"] for r in rows)),
        "failures": [
            {"id": r["id"], "status": r["status"], "first_error": (r["errors"] or [""])[0][:300]}
            for r in rows if r["status"] != OK
        ],
    }


def main():
    cfg = load_config()
    checker = AxleChecker(cfg["axle"])

    print("ProofNet-Verified: loading and compiling references")
    items = proofnet.build_items(cfg["data"]["proofnet_verified"])
    pnv_rows = compile_all(checker, items, RUN_DIR / "proofnet_compile.jsonl")

    split, together = make_split(items, cfg["seed"], cfg["split"])
    table = per_textbook_counts(items, split)
    (ROOT / "data/splits.json").write_text(json.dumps(
        {"seed": cfg["seed"], "sizes": {k: len(v) for k, v in split.items()},
         "kept_together": together, "per_textbook": table, **split},
        indent=1,
    ) + "\n")

    print("miniF2F: loading and compiling references")
    mf_items = minif2f.load_raw_items(cfg["data"]["minif2f"])
    mf_rows = compile_all(checker, mf_items, RUN_DIR / "minif2f_compile.jsonl")
    ok_ids = {r["id"] for r in mf_rows if r["status"] == OK}
    minif2f.save_usable([it for it in mf_items if it["id"] in ok_ids])

    summary = {
        "proofnet_reference_compile": compile_summary(pnv_rows),
        "split": {"seed": cfg["seed"], "sizes": {k: len(v) for k, v in split.items()},
                  "kept_together": together, "per_textbook": table},
        "minif2f_reference_compile": compile_summary(mf_rows),
        "minif2f_usable": len(ok_ids),
        "minif2f_dropped": len(mf_rows) - len(ok_ids),
        "axle_api_calls_this_run": checker.api_calls,
    }
    (RUN_DIR / "summary.json").write_text(json.dumps(summary, indent=1) + "\n")
    print(json.dumps({k: v for k, v in summary.items() if k != "split"}, indent=1)[:3000])

    outages = sum(r["status"] == OUTAGE for r in pnv_rows + mf_rows)
    if outages:
        print(f"{outages} AXLE outages; rerun to retry them (everything else is cached)")
        sys.exit(1)


def report():
    s = json.loads((RUN_DIR / "summary.json").read_text())
    pnv, mf = s["proofnet_reference_compile"], s["minif2f_reference_compile"]
    print(f"- ProofNet-Verified reference compile: {pnv['compiled']}/{pnv['total']} ({pnv['by_status']})")
    for f in pnv["failures"]:
        print(f"  - {f['id']}: {f['status']}: {f['first_error'][:120]}")
    print(f"- Split sizes (seed {s['split']['seed']}): {s['split']['sizes']}; kept together: {s['split']['kept_together']}")
    print("\n| Textbook | Total | Train | Val | Test |\n| --- | --- | --- | --- | --- |")
    for tb, r in s["split"]["per_textbook"].items():
        print(f"| {tb} | {r['total']} | {r['train']} | {r['val']} | {r['test']} |")
    print(f"\n- miniF2F: {s['minif2f_usable']} usable, {s['minif2f_dropped']} dropped of {mf['total']} ({mf['by_status']})")
    reasons = Counter(f["first_error"].split("error")[-1].strip(" :")[:50] for f in mf["failures"])
    for reason, n in reasons.most_common():
        print(f"  - {n} items: {reason!r}")

    print("\n5 random raw train examples (seed 0):")
    items = proofnet.read_jsonl(proofnet.ITEMS_PATH)
    status = {r["id"]: r["status"] for r in proofnet.read_jsonl(RUN_DIR / "proofnet_compile.jsonl")}
    split = json.loads((ROOT / "data/splits.json").read_text())
    split_of = {i: k for k in ("train", "val", "test") for i in split[k]}
    train = [it for it in items if split_of[it["id"]] == "train"]
    for it in random.Random(0).sample(train, 5):
        print(f"\n[{it['id']} | {it['textbook']} | {split_of[it['id']]} | compile: {status[it['id']]}]")
        print("English:", it["informal_stmt"])
        print(it["formal_stmt"])


if __name__ == "__main__":
    report() if "--report" in sys.argv else main()
