"""Chunk 7: exploratory analyses and the writeup checks.

Usage: python -m scripts.chunk7 candidate-truth | compile-errors | prompt-lengths | facts | check

candidate-truth (exploratory): truth labels for the compiled outputs GEPA saved on the 70 validation items
(certificate first, then the reference judge, Deviation 4's re-ask for missing verdicts), cached and
charged to chunk 7. Writes runs/chunk7/candidate_truth.jsonl.gz, candidate_truth_summary.json and
figures/exploratory_judge_vs_truth_iterations.png.

compile-errors (exploratory): arms A and B's non-compiling test outputs re-checked through AXLE and
bucketed by first Lean error, into runs/chunk7/compile_errors.json.

prompt-lengths: word counts of the seed and optimized prompts, into runs/chunk7/prompt_lengths.json.

facts: derived counts the writeup cites (Deviation 4 totals), into runs/chunk7/writeup_facts.json.

check: every number in writeup/writeup.md against writeup/numbers.json and its JSON sources, an em dash
scan, and a secret scan of the whole git history, into runs/chunk7/check.json.
"""
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

from src.axle_check import AxleChecker
from src.chunk7 import candidate_files, candidate_summary, candidate_truth_row, check_numbers, compile_errors, em_dashes
from src.config import ROOT, load_config, load_env
from src.data.firewall import gepa_items, heldout_items
from src.final_eval import deviation4, read_rows, write_rows
from src.llm import LLMClient, spent

OUT = ROOT / "runs/chunk7"
GEPA_RUNS = ("B_s0", "B_s1", "B_s2", "D_s0", "D_s1", "D_s2")


def candidate_truth(cfg):
    checker, client = AxleChecker(cfg["axle"]), LLMClient(cfg, 7, run_id="candidate_truth")
    items = {it["id"]: it for it in gepa_items("val")}
    jobs = [(run_id, cand, row) for run_id in GEPA_RUNS for cand, rows in candidate_files(ROOT / "runs" / run_id) for row in rows]
    before = spent(7)
    with ThreadPoolExecutor(cfg["generation"]["workers"]) as pool:
        rows = list(pool.map(lambda j: candidate_truth_row(cfg, checker, client, *j, items[j[2]["item_id"]]), jobs))
    compiled = [r for r in rows if r["compiled"]]
    fixed = iter(deviation4(cfg, compiled, items, client))  # rows with nothing missing come back unchanged
    rows = [next(fixed) if r["compiled"] else r for r in rows]
    write_rows(OUT / "candidate_truth.jsonl.gz", rows)
    summary = {"note": "exploratory", "evaluations": len(rows), "compiled": len(compiled),
               "certified": sum(r["certified"] for r in rows), "truth_missing": sum(r["truth_label"] is None for r in rows),
               "reasked": sum(bool((r.get("deviation4") or {}).get("ref")) for r in rows),
               "usd": spent(7) - before, "runs": candidate_summary(rows)}
    for run_id in GEPA_RUNS:  # the judge score must equal GEPA's own aggregate for each candidate
        gepa = json.loads((ROOT / "runs" / run_id / "candidates.json").read_text())["val_aggregate_scores"]
        summary.setdefault("judge_matches_gepa", {})[run_id] = all(
            abs(c["judge"] - 100 * gepa[c["candidate"]]) < 1e-9 for c in summary["runs"][run_id])
    (OUT / "candidate_truth_summary.json").write_text(json.dumps(summary, indent=1) + "\n")
    figure(summary, ROOT / "figures/exploratory_judge_vs_truth_iterations.png")
    return {k: v for k, v in summary.items() if k != "runs"}


def figure(summary, path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(1, 2, figsize=(10, 3.8), sharey=False)
    for ax, (prefix, model) in zip(axes, (("B", "Qwen3-8B (arm B)"), ("D", "ReForm-8B (arm D)"))):
        for k, run_id in enumerate(r for r in GEPA_RUNS if r.startswith(prefix)):
            cands = summary["runs"][run_id]
            x = [c["candidate"] for c in cands]
            color = f"C{k}"
            ax.plot(x, [c["judge"] for c in cands], "-o", color=color, ms=3, label=f"seed {run_id[-1]} judge")
            ax.plot(x, [c["truth"] for c in cands], "--s", color=color, ms=3, label=f"seed {run_id[-1]} truth")
        ax.set_title(model)
        ax.set_xlabel("candidate, in the order GEPA found it")
        ax.set_ylabel("score on the 70 validation items (%)")
        ax.legend(fontsize=7, ncol=2)
    fig.suptitle("Exploratory: judge score (solid) vs truth score (dashed) over GEPA's candidates")
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=150)


def compile_error_breakdown(cfg):
    rows = [r for arm in ("A", "B") for r in read_rows(ROOT / f"runs/final/{arm}.jsonl.gz")]
    items = {it["id"]: it for it in heldout_items("test", cfg)}
    return {"note": "exploratory", **compile_errors(rows, AxleChecker(cfg["axle"]), items)}


def check():
    w = ROOT / "writeup"
    entries = json.loads((w / "numbers.json").read_text())
    numbers = check_numbers((w / "writeup.md").read_text(), entries, lambda s: json.loads((ROOT / s).read_text()))
    files = [p for p in [*w.glob("*.md"), ROOT / "README.md", ROOT / "LOG.md", *ROOT.glob("src/**/*.py"),
                         *ROOT.glob("scripts/*.py"), *ROOT.glob("tests/*.py")] if p.exists()]
    dashes = em_dashes(files)
    scan = subprocess.run([sys.executable, str(ROOT / "scripts/secret_scan.py"), "--history"], capture_output=True, text=True)
    out = {"numbers": numbers, "em_dashes": dashes, "files_scanned_for_em_dashes": len(files),
           "secret_scan_history": {"ok": scan.returncode == 0, "output": scan.stdout.strip().splitlines()[-1:]}}
    out["ok"] = numbers["ok"] and not dashes and out["secret_scan_history"]["ok"]
    return out


def main(argv):
    OUT.mkdir(parents=True, exist_ok=True)
    mode = argv[:1]
    if mode == ["candidate-truth"]:
        load_env()
        print(json.dumps(candidate_truth(load_config()), indent=1))
    elif mode == ["compile-errors"]:
        load_env()
        out = compile_error_breakdown(load_config())
        (OUT / "compile_errors.json").write_text(json.dumps(out, indent=1) + "\n")
        print(json.dumps(out, indent=1))
    elif mode == ["prompt-lengths"]:
        words = lambda p: len(p.read_text().split())
        out = {"seed": {"A": words(ROOT / "prompts/arm_A.txt"), "C": words(ROOT / "prompts/arm_C.txt")},
               "optimized": {r: words(ROOT / "runs" / r / "best_prompt.txt") for r in GEPA_RUNS}}
        (OUT / "prompt_lengths.json").write_text(json.dumps(out, indent=1) + "\n")
        print(json.dumps(out, indent=1))
    elif mode == ["facts"]:
        d4 = json.loads((ROOT / "runs/chunk5_deviation4.json").read_text())
        rows = [r for arm in d4["arms"] for r in read_rows(ROOT / f"runs/final/{arm}.jsonl.gz")]
        out = {"ref_verdicts_missing_before": sum(n for a in d4["arms"].values() for n in a["ref"].values()),
               "ref_verdicts_filled": sum(n for a in d4["arms"].values() for k, n in a["ref"].items() if k != "still_missing"),
               "ref_still_missing": {ds: sum(r["ref_missing"] for r in rows if r["dataset"] == ds) for ds in ("test", "minif2f")},
               "gepa_saved_evaluations": sum(v["saved_evaluations"] for v in d4["gepa_opt_judge_missing"].values()),
               "gepa_opt_judge_missing": sum(v["missing"] for v in d4["gepa_opt_judge_missing"].values())}
        (OUT / "writeup_facts.json").write_text(json.dumps(out, indent=1) + "\n")
        print(json.dumps(out, indent=1))
    elif mode == ["check"]:
        out = check()
        (OUT / "check.json").write_text(json.dumps(out, indent=1) + "\n")
        print(json.dumps(out, indent=1))
        sys.exit(0 if out["ok"] else 1)
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
