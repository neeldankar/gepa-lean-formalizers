"""Final evaluation (chunk 5): every arm's final prompt on test and miniF2F (arm F: test only).

One row per (arm, GEPA seed, dataset, item, sample) with the raw output, the judge score, the truth
score and memorization matches (test outputs only; miniF2F is not ProofNet). Rows with an AXLE
outage keep `outage: true`; rerun to fill them (everything else is cached).
"""
import gzip
import json
from concurrent.futures import ThreadPoolExecutor

from src.data.firewall import heldout_items
from src.generate import generate
from src.prompting import load_fewshot, load_instructions
from src.scoring import memorization
from src.scoring.score import judge_score, prepare, truth_score


def arm_prompts(cfg, arm, runs_dir):
    """[(run_id, gepa_seed, instructions, fewshot)]: the fixed prompt, or each GEPA run's best-on-val
    prompt, with the arm's (or the GEPA run's) fixed few-shot block."""
    spec = cfg["arms"][arm]
    if "gepa_runs" in spec:
        return [(r, cfg["gepa"]["runs"][r]["seed"], (runs_dir / r / "best_prompt.txt").read_text().rstrip("\n"),
                 load_fewshot(cfg["gepa"]["runs"][r].get("fewshot"))) for r in spec["gepa_runs"]]
    return [(None, None, load_instructions(spec["prompt"]), load_fewshot(spec.get("fewshot")))]


def score_row(cfg, arm, model_key, run_id, seed, dataset, instructions, item, sample, gen, judge, checker, fewshot=""):
    out = generate(gen, cfg, model_key, instructions, item, sample, fewshot=fewshot)
    p = prepare(checker, item, out["text"])
    js = judge_score(checker, judge, cfg, item, out["text"], prepared=p)
    ts = truth_score(checker, judge, cfg, item, out["text"], prepared=p)
    cert, ref = ts["certificate"] or {}, ts["ref_judge"] or {}
    return {
        "arm": arm, "run_id": run_id, "gepa_seed": seed, "dataset": dataset, "item_id": item["id"], "sample": sample,
        "output": out["text"], "finish_reason": out["finish_reason"],
        "completion_tokens": (out.get("usage") or {}).get("completion_tokens"),
        "extracted": p["extracted"], "normalized": p["normalized"], "format_failure": p["format_failure"],
        "compile_status": p["compile_status"], "compiled": p["compiled"],
        "judge_verdict": (js["judge"] or {}).get("verdict"), "judge_reason": (js["judge"] or {}).get("reason"),
        "judge_score": js["judge_score"], "judge_missing": js["judge_missing"], "certified": cert.get("certified", False),
        "cert_status": cert.get("status"), "cert_directions": cert.get("directions"),
        "ref_verdict": ref.get("verdict"), "ref_reason": ref.get("reason"), "ref_error_tag": ref.get("error_tag"),
        "ref_missing": ts["ref_missing"], "truth_label": ts["truth_label"], "truth_source": ts["truth_source"],
        # a missing judge verdict is not an outage: it is kept, counted, and left out of the rates
        "outage": ts["truth_source"] == "outage" or (js["judge_score"] is None and not js["judge_missing"]), "memorized": [],
    }


def eval_arm(cfg, arm, gen, judge, checker, runs_dir, root, mem_index=None, items_for=None):
    """items_for(dataset) -> (label, items) replaces the held-out loader; only the chunk 5 dry run uses it,
    with train items standing in for test and miniF2F, so it never touches either."""
    spec = cfg["arms"][arm]
    datasets = ["test"] if spec.get("test_only") else ["test", "minif2f"]
    jobs = []
    for name in datasets:
        if items_for:
            dataset, items = items_for(name)
        else:
            dataset, items = name, heldout_items(name, cfg, root=root, runs_dir=runs_dir)
        for run_id, seed, instructions, fewshot in arm_prompts(cfg, arm, runs_dir):
            for item in items:
                for sample in range(cfg["generation"]["samples"]):
                    jobs.append((run_id, seed, dataset, instructions, item, sample, fewshot))
    with ThreadPoolExecutor(cfg["generation"]["workers"]) as pool:
        rows = list(pool.map(lambda j: score_row(cfg, arm, spec["model"], *j[:6], gen, judge, checker, fewshot=j[6]), jobs))
    if mem_index is not None:
        test = [(r, j[4]) for r, j in zip(rows, jobs) if r["dataset"].endswith("test") and r["normalized"]]
        matches = memorization.exact_matches(checker, mem_index, [it for _, it in test], [r["normalized"] for r, _ in test])
        for (r, _), m in zip(test, matches):
            r["memorized"] = m
    return rows


def write_rows(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def read_rows(path):
    with gzip.open(path, "rt") as f:
        return [json.loads(line) for line in f]
