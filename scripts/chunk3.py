"""Chunk 3: runner checks.

Steps (write into runs/chunk3/ and summary.json there; no arguments runs them all):
  refs     the 4 references that need autoImplicit (and pnv_092, which needs maxRecDepth): a
           hand-written candidate binding the auto-bound name compiles with autoImplicit off and gets a
           certificate. Reference judge only on train and validation items (no model calls on test).
  smoke    one live call through Together with the same generation client code, on a train item.
  dryrun   end to end on mocks: six GEPA runs, final eval of A to D and F, analysis, results.json and
           both figures, all under runs/chunk3/dryrun/ (mock costs go to its own costs file).
  costs    chunk 3 costs from runs/costs.jsonl.
`report` prints the LOG.md lines and 5 random dry-run examples.
"""
import copy
import json
import random
import sys

from src.analysis import analyze, figures
from src.axle_check import AxleChecker
from src.config import ROOT, load_config
from src.costs import summarize
from src.data.proofnet import ITEMS_PATH, read_jsonl, write_jsonl
from src.final_eval import eval_arm, read_rows, write_rows
from src.generate import formalizer_client, generate
from src.llm import LLMClient
from src.mocks import MockAxleClient, MockPosts
from src.prompting import load_instructions
from src.runner import run_gepa
from src.scoring import judge as judges
from src.scoring.certificate import certificate
from src.scoring.compile import compile_candidate
from src.scoring.normalize import normalize_statement
from src.scoring.score import judge_score, prepare, truth_score

CHUNK = 3
RUN_DIR = ROOT / "runs/chunk3"
SUMMARY = RUN_DIR / "summary.json"
DRY = RUN_DIR / "dryrun"

# Hand-written candidates: the reference with its auto-bound name declared explicitly.
REF_CANDIDATES = {
    "pnv_025": lambda s: s.replace("{V : Type*}", "{F V : Type*}", 1),
    "pnv_207": lambda s: s.replace("{V : Type*}", "{F V : Type*}", 1),
    "pnv_208": lambda s: s.replace("{V : Type*}", "{F V : Type*}", 1),
    "pnv_280": lambda s: s.replace("{a : ℤ}", "{a : ℤ} {f_a : ℕ → ℕ → ℕ}", 1),
    "pnv_092": lambda s: s,  # needs `set_option maxRecDepth 2048 in`; exact copy
}


def load_summary():
    return json.loads(SUMMARY.read_text()) if SUMMARY.exists() else {}


def save_summary(summary):
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    SUMMARY.write_text(json.dumps(summary, indent=1, ensure_ascii=False) + "\n")


def refs(cfg, summary):
    items = {it["id"]: it for it in read_jsonl(ITEMS_PATH)}
    splits = json.loads((ROOT / "data/splits.json").read_text())
    split_of = {i: k for k in ("train", "val", "test") for i in splits[k]}
    checker = AxleChecker(cfg["axle"])
    client = LLMClient(cfg, CHUNK)
    rows = []
    for item_id, make in REF_CANDIDATES.items():
        item = items[item_id]
        ref = normalize_statement(item["formal_stmt"])
        cand = normalize_statement(make(ref))
        compiled = compile_candidate(checker, item, cand)
        cert = certificate(checker, item, cand, ref)
        row = {"id": item_id, "name": item["name"], "split": split_of[item_id], "candidate": cand,
               "candidate_compiles_autoimplicit_off": compiled.passed, "certified": cert["certified"],
               "cert_status": cert["status"], "directions": cert["directions"], "ref_judge": None}
        if split_of[item_id] in ("train", "val"):
            row["ref_judge"] = judges.reference_judge(client, cfg, item["informal_stmt"], ref, cand)
        else:
            row["ref_judge"] = "not called: test item (no model calls on test before chunk 5)"
        rows.append(row)
    write_jsonl(RUN_DIR / "refs.jsonl", rows)
    summary["refs"] = [{k: r[k] for k in ("id", "name", "split", "candidate_compiles_autoimplicit_off", "certified")}
                       | {"ref_judge_verdict": r["ref_judge"]["verdict"] if isinstance(r["ref_judge"], dict) else None}
                       for r in rows]


def smoke(cfg, summary):
    item = next(it for it in read_jsonl(ITEMS_PATH) if it["id"] == "pnv_075")  # a train item
    gen = formalizer_client(cfg, "smoke", CHUNK, run_id="smoke")
    reply = generate(gen, cfg, "smoke", load_instructions("prompts/arm_A.txt"), item)
    checker, judge = AxleChecker(cfg["axle"]), LLMClient(cfg, CHUNK, run_id="smoke")
    p = prepare(checker, item, reply["text"])
    js = judge_score(checker, judge, cfg, item, reply["text"], prepared=p)
    ts = truth_score(checker, judge, cfg, item, reply["text"], prepared=p)
    record = {"item_id": item["id"], "model": cfg["models"]["smoke"]["served_name"], "output": reply["text"],
              "finish_reason": reply["finish_reason"], "usage": reply.get("usage"), "normalized": p["normalized"],
              "compiled": p["compiled"], "judge": js["judge"], "judge_score": js["judge_score"],
              "certificate": ts["certificate"], "ref_judge": ts["ref_judge"], "truth_label": ts["truth_label"]}
    (RUN_DIR / "smoke.json").write_text(json.dumps(record, indent=1, ensure_ascii=False) + "\n")
    summary["smoke"] = {k: record[k] for k in ("item_id", "model", "finish_reason", "compiled", "judge_score", "truth_label")}


def dryrun(cfg, summary):
    cfg = copy.deepcopy(cfg)
    cfg["gepa"]["max_metric_calls"] = 150
    cfg["axle"]["outage_backoff_seconds"] = 0
    cfg["analysis"]["bootstrap_resamples"] = 2000
    cfg["arms"] = {k: v for k, v in cfg["arms"].items() if k != "E"}  # arm E's prompt is Neel's, written in chunk 4
    posts, costs = MockPosts(), DRY / "costs.jsonl"
    costs.unlink(missing_ok=True)
    kw = dict(cache_dir=ROOT / "cache/dryrun/llm", costs_path=costs)
    gen = LLMClient(cfg, CHUNK, post=posts.formalizer, base_url="http://mock", api_key_env=None, **kw)
    judge = LLMClient(cfg, CHUNK, post=posts.judge, **kw)
    refl = LLMClient(cfg, CHUNK, post=posts.reflection, **kw)
    checker = AxleChecker(cfg["axle"], client_factory=MockAxleClient, cache_dir=ROOT / "cache/dryrun/axle")
    runs = {run_id: run_gepa(cfg, run_id, gen, judge, refl, checker, runs_dir=DRY) for run_id in cfg["gepa"]["runs"]}
    rows = []
    for arm in cfg["arms"]:
        arm_rows = eval_arm(cfg, arm, gen, judge, checker, DRY, ROOT)
        write_rows(DRY / "final" / f"{arm}.jsonl.gz", arm_rows)
        rows += arm_rows
    results = analyze(rows, cfg)
    (DRY / "results.json").write_text(json.dumps(results, indent=1) + "\n")
    figures(results, DRY / "figures")
    summary["dryrun"] = {
        "gepa_runs": runs,
        "final_rows": {arm: sum(r["arm"] == arm for r in rows) for arm in cfg["arms"]},
        "contrasts": results["confirmatory"]["contrasts"],
        "figures": sorted(p.name for p in (DRY / "figures").glob("*.png")),
        "mock_calls": posts.calls,
    }


def costs(cfg, summary):
    rows = [r for r in read_jsonl(ROOT / "runs/costs.jsonl") if r["chunk"] == CHUNK]
    summary["costs"] = summarize(rows)


STEPS = {"refs": refs, "smoke": smoke, "dryrun": dryrun, "costs": costs}


def report():
    s = load_summary()
    print("- autoImplicit / option references (hand-written candidate binds the auto-bound name):")
    for r in s["refs"]:
        print(f"  - {r['id']} ({r['name']}, {r['split']}): candidate compiles with autoImplicit off: "
              f"{r['candidate_compiles_autoimplicit_off']}; certified: {r['certified']}; reference judge: {r['ref_judge_verdict']}")
    sm = s["smoke"]
    print(f"- Smoke call ({sm['model']}, {sm['item_id']}): finish {sm['finish_reason']}, compiled {sm['compiled']}, "
          f"judge score {sm['judge_score']}, truth {sm['truth_label']}")
    d = s["dryrun"]
    print("- Dry run on mocks:")
    for run_id, r in d["gepa_runs"].items():
        print(f"  - {run_id}: {r['status']}, {r['total_metric_calls']} metric calls, best val {r['best_val']:.3f}")
    print(f"  - final rows per arm: {d['final_rows']}; figures: {d['figures']}")
    for name, c in d["contrasts"].items():
        print(f"  - {name}: {c['estimate']:.1f} [{c['ci'][0]:.1f}, {c['ci'][1]:.1f}] {c['decision']}")
    c = s["costs"]
    print(f"- Chunk 3 cost: ${c['usd_total']:.4f}; by purpose: "
          + ", ".join(f"{k} {v['calls']} calls ${v['usd']:.4f}" for k, v in c["by_purpose"].items()))
    print("\n5 random dry-run rows (seed 0):")
    rows = [r for p in sorted((DRY / "final").glob("*.jsonl.gz")) for r in read_rows(p)]
    for r in random.Random(0).sample(rows, 5):
        print(f"\n[{r['arm']} {r['run_id'] or ''} | {r['dataset']} {r['item_id']} | judge {r['judge_score']} | truth {r['truth_label']} ({r['truth_source']})]")
        print("normalized:", r["normalized"])


def main():
    if sys.argv[1:] == ["report"]:
        return report()
    cfg = load_config()
    summary = load_summary()
    for name in sys.argv[1:] or list(STEPS):
        print(f"== {name}")
        STEPS[name](cfg, summary)
        save_summary(summary)


if __name__ == "__main__":
    main()
