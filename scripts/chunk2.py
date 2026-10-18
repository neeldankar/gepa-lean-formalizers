"""Chunk 2: scoring checks.

Steps (all write into runs/chunk2/ and summary.json there; no arguments runs them all):
  prebuild      diff the duplicate Rudin_exercise_4_8a rows; compile every reference with autoImplicit
                off once, for information only (references are still scored as shipped).
  stripper      run AXLE's remove_comments and ours on every strip.CASES entry; the winner must
                match scoring.stripper in config.yaml.
  golden        run tests/golden/cases.jsonl (train items only) through both scores.
  memorization  build the exact-match index; check every train reference matches itself.
  labeling      demo labeling page from the compiled golden candidates.
  costs         judge cost per call from runs/costs.jsonl.
`report` (not part of the default run) prints the LOG.md tables and 5 random golden examples.
"""
import json
import sys
from collections import Counter

import random

from axle import remove_comments

from src.axle_check import OK, AxleChecker
from src.llm import LLMClient
from src.scoring import memorization
from src.scoring.golden import run_golden, train_items
from src.scoring.labeling import build_page
from src.scoring.strip import CASES, squash, strip_comments
from src.config import ROOT, load_config
from src.data.proofnet import ITEMS_PATH, read_jsonl, write_jsonl
from src.scoring.compile import candidate_content

RUN_DIR = ROOT / "runs/chunk2"
SUMMARY = RUN_DIR / "summary.json"


def load_summary():
    return json.loads(SUMMARY.read_text()) if SUMMARY.exists() else {}


def save_summary(summary):
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    SUMMARY.write_text(json.dumps(summary, indent=1, ensure_ascii=False) + "\n")


def duplicate_diff(items, splits):
    split_of = {i: k for k in ("train", "val", "test") for i in splits[k]}
    by_name = {}
    for it in items:
        by_name.setdefault(it["name"], []).append(it)
    out = []
    for name, group in sorted(by_name.items()):
        if len(group) < 2:
            continue
        a, b = group[0], group[1]
        fields = ("informal_stmt", "header", "helper", "formal_stmt")
        out.append({
            "name": name,
            "ids": [a["id"], b["id"]],
            "splits": [split_of[a["id"]], split_of[b["id"]]],
            "identical": all(a[f] == b[f] for f in fields),
            "differs_in": [f for f in fields if a[f] != b[f]],
            "values": {f: [a[f], b[f]] for f in fields if a[f] != b[f]},
        })
    return out


def prebuild(cfg, summary):
    items = read_jsonl(ITEMS_PATH)
    splits = json.loads((ROOT / "data/splits.json").read_text())
    summary["duplicates"] = duplicate_diff(items, splits)

    checker = AxleChecker(cfg["axle"])
    results = checker.check_many([candidate_content(it, it["formal_stmt"]) for it in items], progress_every=100)
    rows = [{"id": it["id"], "status": r.status, "errors": r.errors} for it, r in zip(items, results)]
    write_jsonl(RUN_DIR / "ref_autoimplicit_off.jsonl", rows)
    summary["references_autoimplicit_off"] = {
        "total": len(rows),
        "compiled": sum(r["status"] == OK for r in rows),
        "by_status": dict(Counter(r["status"] for r in rows)),
        "failures": [{"id": r["id"], "status": r["status"], "first_error": (r["errors"] or [""])[0][:300]}
                     for r in rows if r["status"] != OK],
    }


def stripper(cfg, summary):
    rows = []
    for name, inp, expected in CASES:
        rows.append({"case": name, "input": inp, "expected": expected,
                     "ours_output": strip_comments(inp), "axle_output": remove_comments(inp),
                     "ours": squash(strip_comments(inp)) == squash(expected),
                     "axle": squash(remove_comments(inp)) == squash(expected)})
    write_jsonl(RUN_DIR / "stripper_contest.jsonl", rows)
    axle_ok = all(r["axle"] for r in rows)
    summary["stripper"] = {
        "cases": len(rows), "ours_passed": sum(r["ours"] for r in rows), "axle_passed": sum(r["axle"] for r in rows),
        "axle_failed": [{"case": r["case"], "axle_output": r["axle_output"]} for r in rows if not r["axle"]],
        "winner": "axle" if axle_ok else "ours", "config": cfg["scoring"]["stripper"],
    }
    if summary["stripper"]["winner"] != cfg["scoring"]["stripper"]:
        raise SystemExit("config.yaml scoring.stripper does not match the contest winner")


def golden(cfg, summary):
    results = run_golden(AxleChecker(cfg["axle"]), LLMClient(cfg, chunk=2), cfg)
    write_jsonl(RUN_DIR / "golden.jsonl", results)
    summary["golden"] = {
        "cases": len(results), "passed": sum(r["passed"] for r in results),
        "certificates": cfg["scoring"]["certificates"],
        "table": [{"case": r["case"],
                   "expected": {k: c["expected"] for k, c in r["checks"].items()},
                   "got": {k: c["got"] for k, c in r["checks"].items()}, "passed": r["passed"]} for r in results],
    }


def memorization_step(cfg, summary):
    checker = AxleChecker(cfg["axle"])
    index, counts = memorization.build_index(checker, cfg["data"]["proofnet_verified"])
    items = list(train_items().values())
    matches = memorization.exact_matches(checker, index, items, [it["formal_stmt"] for it in items])
    summary["memorization"] = {
        "sources": counts, "skipped": memorization.SKIPPED, "distinct_keys": len(index),
        "train_references_matching_proofnet_verified": sum("ProofNet-Verified" in m for m in matches),
        "train_references": len(items),
    }


def labeling(cfg, summary):
    results = [r for r in read_jsonl(RUN_DIR / "golden.jsonl") if r["normalized"] and r["compile_status"] == OK]
    items = train_items()
    from src.scoring.normalize import normalize_statement
    records = [{"label_id": f"demo-{i + 1:02d}", "english": items[r["item_id"]]["informal_stmt"],
                "reference": normalize_statement(items[r["item_id"]]["formal_stmt"]), "candidate": r["normalized"]}
               for i, r in enumerate(results)]
    random.Random(0).shuffle(records)
    build_page(LLMClient(cfg, chunk=2), cfg, records, RUN_DIR / "labeling_demo.html", "chunk2-demo")
    summary["labeling_demo"] = {"records": len(records), "path": "runs/chunk2/labeling_demo.html"}


def costs(cfg, summary):
    rows = [r for r in read_jsonl(ROOT / "runs/costs.jsonl") if r["chunk"] == 2]
    per = {}
    for r in rows:
        p = per.setdefault(r["purpose"], {"model": r["model"], "calls": 0, "usd": 0.0, "prompt_tokens": 0, "completion_tokens": 0})
        p["calls"] += 1
        p["usd"] += r["usd"]
        p["prompt_tokens"] += r["prompt_tokens"]
        p["completion_tokens"] += r["completion_tokens"]
    for p in per.values():
        p["usd_per_call"] = p["usd"] / p["calls"]
    summary["costs"] = {"paid_calls": len(rows), "usd_total": sum(r["usd"] for r in rows), "by_purpose": per}


STEPS = {"prebuild": prebuild, "stripper": stripper, "golden": golden, "memorization": memorization_step,
         "labeling": labeling, "costs": costs}


def fmt(v):
    return json.dumps(v, ensure_ascii=False) if not isinstance(v, str) else v


def report():
    s = load_summary()
    ref = s["references_autoimplicit_off"]
    print(f"- References compiled with autoImplicit off (information only): {ref['compiled']}/{ref['total']}")
    for f in ref["failures"]:
        print(f"  - {f['id']}: {f['first_error'].splitlines()[0][:110]}")
    d = s["duplicates"][0]
    print(f"- Duplicate {d['name']} ({', '.join(d['ids'])}, splits {d['splits']}): identical {d['identical']}, differs in {d['differs_in']}")
    st = s["stripper"]
    print(f"- Stripper contest: ours {st['ours_passed']}/{st['cases']}, AXLE remove_comments {st['axle_passed']}/{st['cases']}; winner: {st['winner']}")
    for f in st["axle_failed"]:
        print(f"  - AXLE failed {f['case']!r}: output {f['axle_output']!r}")
    g = s["golden"]
    print(f"- Golden cases: {g['passed']}/{g['cases']} pass; certificates: {'on' if g['certificates'] else 'off'}")
    print("\n| Case | Expected | Got | Pass |\n| --- | --- | --- | --- |")
    for r in g["table"]:
        exp = "; ".join(f"{k}={fmt(v)}" for k, v in r["expected"].items())
        got = "; ".join(f"{k}={fmt(v)}" for k, v in r["got"].items())
        print(f"| {r['case']} | {exp} | {got} | {'yes' if r['passed'] else 'NO'} |")
    c = s["costs"]
    print(f"\n- Judge cost per call (chunk 2, ${c['usd_total']:.4f} over {c['paid_calls']} paid calls):")
    for purpose, p in c["by_purpose"].items():
        print(f"  - {purpose} ({p['model']}): {p['calls']} calls, ${p['usd_per_call']:.6f} per call")
    m = s["memorization"]
    print(f"- Memorization index: {m['distinct_keys']} distinct statements; sources {m['sources']}; skipped {m['skipped']}; "
          f"train references matching themselves: {m['train_references_matching_proofnet_verified']}/{m['train_references']}")

    print("\n5 random golden examples (seed 0):")
    for r in random.Random(0).sample(read_jsonl(RUN_DIR / "golden.jsonl"), 5):
        print(f"\n[{r['case']} | {r['item_id']} | compile: {r['compile_status']} | truth from: {r['truth_source']}]")
        print("normalized:", r["normalized"])
        print("opt judge:", r["judge"])
        print("ref judge:", r["ref_judge"])
        print("certificate:", (r["certificate"] or {}).get("directions"))


def main():
    if sys.argv[1:] == ["report"]:
        return report()
    cfg = load_config()
    summary = load_summary()
    for name in sys.argv[1:] or list(STEPS):
        print(f"== {name}")
        STEPS[name](cfg, summary)
        save_summary(summary)
    print(json.dumps(summary, indent=1, ensure_ascii=False)[:4000])


if __name__ == "__main__":
    main()
