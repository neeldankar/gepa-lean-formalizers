"""Final evaluation (chunk 5): every arm's final prompt on test and miniF2F (arm F: test only).

One row per (arm, GEPA seed, dataset, item, sample) with the raw output, the judge score, the truth
score and memorization matches (test outputs only; miniF2F is not ProofNet). Rows with an AXLE
outage keep `outage: true`; rerun to fill them (everything else is cached).

Deviation 3: for an arm with `missing_on_api_failure` (arm F), a generation call that still fails after
its retries becomes a `generation_missing` row: no output, no scores, left out of every rate and
counted as missing, never a format failure or a job-ending error.
"""
import gzip
import json
from concurrent.futures import ThreadPoolExecutor

from src.data.firewall import heldout_items
from src.generate import generate
from src.llm import LLMError
from src.prompting import load_fewshot, load_instructions
from src.scoring import judge, memorization
from src.scoring.normalize import normalize_statement
from src.scoring.score import judge_score, prepare, truth_from, truth_score


def arm_prompts(cfg, arm, runs_dir):
    """[(run_id, gepa_seed, instructions, fewshot)]: the fixed prompt, or each GEPA run's best-on-val
    prompt, with the arm's (or the GEPA run's) fixed few-shot block."""
    spec = cfg["arms"][arm]
    if "gepa_runs" in spec:
        return [(r, cfg["gepa"]["runs"][r]["seed"], (runs_dir / r / "best_prompt.txt").read_text().rstrip("\n"),
                 load_fewshot(cfg["gepa"]["runs"][r].get("fewshot"))) for r in spec["gepa_runs"]]
    return [(None, None, load_instructions(spec["prompt"]), load_fewshot(spec.get("fewshot")))]


def missing_row(arm, run_id, seed, dataset, item, sample, error):
    """A generation that failed after its retries (Deviation 3): kept so the item has a row, scored nowhere."""
    return {
        "arm": arm, "run_id": run_id, "gepa_seed": seed, "dataset": dataset, "item_id": item["id"], "sample": sample,
        "generation_missing": True, "generation_error": str(error)[:500],
        "output": None, "finish_reason": None, "completion_tokens": None, "extracted": None, "normalized": None,
        "format_failure": None, "compile_status": None, "compiled": None,
        "judge_verdict": None, "judge_reason": None, "judge_score": None, "judge_missing": False,
        "certified": False, "cert_status": None, "cert_directions": None,
        "ref_verdict": None, "ref_reason": None, "ref_error_tag": None, "ref_missing": False,
        "truth_label": None, "truth_source": "generation_missing", "outage": False, "memorized": [],
    }


def score_row(cfg, arm, model_key, run_id, seed, dataset, instructions, item, sample, gen, judge, checker, fewshot=""):
    try:
        out = generate(gen, cfg, model_key, instructions, item, sample, fewshot=fewshot)
    except LLMError as e:  # out of retries; only arms flagged in config record it instead of failing the arm
        if not cfg["arms"][arm].get("missing_on_api_failure"):
            raise
        return missing_row(arm, run_id, seed, dataset, item, sample, f"{type(e).__name__}: {e}")
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
        "generation_missing": False,
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


def _refill(stored, need_tag, ask, samples):
    """(verdict dict, note): the stored reply re-parsed, else one re-ask per sample index until one parses."""
    parsed = judge.parse_json_reply(stored or "", need_tag)
    if parsed:
        return parsed, "reparsed"
    for n, sample in enumerate(samples, 1):
        res = ask([sample])
        if not judge.is_missing(res["verdict"]):
            return res, f"reasked:{n}"
    return res, "still_missing"


def deviation4(cfg, rows, items, client):
    """Deviation 4 (Neel, 2026-10-23, before any scores were seen): fill missing judge verdicts in final rows.
    Reference judge: the fixed parser on the stored reply, else up to `attempts` re-asks (same prompt,
    temperature 0, `ref_max_tokens`). Optimization judge: the same with its original settings. Truth is
    recomputed under the frozen rule (certificate first). Rows with nothing missing come back unchanged."""
    d4 = cfg["judges"]["deviation4"]
    samples = range(d4["first_sample"], d4["first_sample"] + d4["attempts"])

    def fix(row):
        if not (row["ref_missing"] or row["judge_missing"]):
            return row
        row, item, note = dict(row), items[row["item_id"]], {}
        if row["ref_missing"]:
            reference = normalize_statement(item["formal_stmt"])
            res, note["ref"] = _refill(row["ref_reason"], True, lambda s: judge.reference_judge(
                client, cfg, item["informal_stmt"], reference, row["normalized"], max_tokens=d4["ref_max_tokens"],
                samples=s), samples)
            row.update(ref_verdict=res["verdict"], ref_reason=res["reason"], ref_error_tag=res.get("error_tag"),
                       ref_missing=judge.is_missing(res["verdict"]))
            row["truth_label"], row["truth_source"] = truth_from(row["certified"], row["ref_verdict"])
        if row["judge_missing"]:
            res, note["opt"] = _refill(row["judge_reason"], False, lambda s: judge.optimization_judge(
                client, cfg, item["informal_stmt"], row["normalized"], samples=s), samples)
            missing = judge.is_missing(res["verdict"])
            row.update(judge_verdict=res["verdict"], judge_reason=res["reason"], judge_missing=missing,
                       judge_score=None if missing else int(res["verdict"] == "faithful"))
        row["deviation4"] = note
        return row

    with ThreadPoolExecutor(cfg["generation"]["workers"]) as pool:
        return list(pool.map(fix, rows))


def write_rows(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def read_rows(path):
    with gzip.open(path, "rt") as f:
        return [json.loads(line) for line in f]
