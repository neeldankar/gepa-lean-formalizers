"""Chunk 7: exploratory analyses and the writeup checks.

Usage: python -m scripts.chunk7 candidate-truth | gap-slope | compile-errors | prompt-names | prompt-lengths | facts | seed-check | check

candidate-truth (exploratory): truth labels for the compiled outputs GEPA saved on the 70 validation items
(certificate first, then the reference judge, Deviation 4's re-ask for missing verdicts), cached and
charged to chunk 7. Writes runs/chunk7/candidate_truth.jsonl.gz, candidate_truth_summary.json and
figures/exploratory_judge_vs_truth_iterations.png.

gap-slope (exploratory): whether judge minus truth grows over GEPA iterations. Per model, a within-run slope
pooled over the three runs, with an item bootstrap (the validation items resampled, the same draw for every
candidate); also without the seed candidate, whose saved outputs the seed pass rewrote (seed-check). Into
runs/chunk7/gap_slope.json, then the figure is redrawn with the result in its caption.

prompt-names (exploratory): the Mathlib-style names in the six optimized prompts, each checked with AXLE as a
constant (bare, then under the GEPA items' opens) or a namespace, with the role the prompt gives it (warned
as nonexistent, in an example of an error, or recommended), into runs/chunk7/prompt_names.json.

compile-errors (exploratory): arms A and B's non-compiling test outputs re-checked through AXLE and
bucketed by first Lean error, into runs/chunk7/compile_errors.json.

prompt-lengths: word counts of the seed and optimized prompts, into runs/chunk7/prompt_lengths.json.

seed-check: per run, the items where the saved seed-candidate outputs differ from the seed scores in GEPA's
state (GEPA re-evaluates the seed on every launch; before the no-overwrite fix that pass replaced the saved
file), into runs/chunk7/seed_pass_check.json.

facts: derived counts the writeup cites (Deviation 4 totals; judge vs truth over GEPA's candidates), into runs/chunk7/writeup_facts.json.

check: every number in writeup/writeup.md and the email drafts against writeup/numbers.json and its JSON sources, an em dash
scan, and a secret scan of the whole git history, into runs/chunk7/check.json.
"""
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

from src.axle_check import OK, OUTAGE, AxleChecker
from src.chunk7 import (candidate_files, candidate_iterations, candidate_summary, candidate_truth_row, check_numbers,
                        compile_errors, defined_names, em_dashes, gap_slope, name_check_contents, prompt_names)
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
    return {k: v for k, v in summary.items() if k != "runs"}


MODELS = (("B", "Qwen3-8B"), ("D", "ReForm-8B"))


def iterations():
    return {run_id: candidate_iterations(ROOT / "runs" / run_id) for run_id in GEPA_RUNS}


def slopes(cfg):
    rows = read_rows(OUT / "candidate_truth.jsonl.gz")
    iters, a = iterations(), cfg["analysis"]
    out = {"note": "exploratory. Slope of (judge score minus truth score) in points per GEPA iteration, within run and "
                   "pooled over a model's three runs; x is the iteration that proposed the candidate (0 = seed). The "
                   "interval resamples the 70 validation items only: candidates share a lineage and are the ones GEPA kept.",
           "resamples": a["bootstrap_resamples"], "seed": a["seed"]}
    seed_pass = json.loads((OUT / "seed_pass_check.json").read_text())
    differ = {r: sum(seed_pass[r]["candidates_with_differences"].values()) for r in GEPA_RUNS}
    out["seed_pass_items_differ"] = {"per_run": differ, "min": min(differ.values()), "max": max(differ.values())}
    for prefix, model in MODELS:
        mine = [r for r in rows if r["run_id"].startswith(prefix)]
        out[prefix] = {"model": model, "all": gap_slope(mine, iters, a["bootstrap_resamples"], a["seed"]),
                       "without_seed_candidate": gap_slope(mine, iters, a["bootstrap_resamples"], a["seed"], exclude={0})}
    return out


def figure(summary, path, slope):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    iters = iterations()
    differ = slope["seed_pass_items_differ"]
    fig, axes = plt.subplots(1, 2, figsize=(10, 5), sharey=False)
    for ax, (prefix, model) in zip(axes, ((p, f"{m} (arm {p})") for p, m in MODELS)):
        for k, run_id in enumerate(r for r in GEPA_RUNS if r.startswith(prefix)):
            cands = summary["runs"][run_id]
            x = [iters[run_id][c["candidate"]] for c in cands]
            color = f"C{k}"
            ax.plot(x, [c["judge"] for c in cands], "-o", color=color, ms=3, label=f"{run_id} judge")
            ax.plot(x, [c["truth"] for c in cands], "--s", color=color, ms=3, label=f"{run_id} truth")
        ax.set_title(model)
        ax.set_xlabel("GEPA iteration that proposed the candidate (0 = seed prompt)")
        ax.set_ylabel("score on the 70 validation items (%)")
        ax.legend(fontsize=7, ncol=2)
    fig.suptitle("Exploratory: judge score (solid) vs truth score (dashed) over GEPA's candidates")
    fmt = lambda s: f"{s['slope']:+.2f} [{s['ci'][0]:.2f}, {s['ci'][1]:.2f}]"
    fig.text(0.01, 0.01, "Gap (judge minus truth), points per iteration, within run, pooled over 3 runs, 95% item bootstrap: "
             + "; ".join(f"{slope[p]['model']} {fmt(slope[p]['all'])}" for p, _ in MODELS) + ".\n"
             + f"Caveat: the saved seed (iteration 0) outputs differ from what GEPA scored on {differ['min']} to {differ['max']} of 70 items "
             + "per run (runs/chunk7/seed_pass_check.json).\nWithout the seed candidates: "
             + "; ".join(f"{slope[p]['model']} {fmt(slope[p]['without_seed_candidate'])}" for p, _ in MODELS) + ".",
             fontsize=7.5, va="bottom")
    fig.tight_layout(rect=(0, 0.1, 1, 1))
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=150)


def name_check(cfg):
    items = gepa_items("train") + gepa_items("val")
    exclude = set().union(*(defined_names(it["helper"]) for it in items))
    opens = sorted({ns for it in items for line in it["header"].splitlines() if line.startswith("open ")
                    for ns in line.split()[1:] if ns != "scoped"})
    opens_line = "open " + " ".join(opens)
    names = {}
    for run_id in GEPA_RUNS:
        for name, v in prompt_names((ROOT / "runs" / run_id / "best_prompt.txt").read_text(), exclude).items():
            e = names.setdefault(name, {"runs": [], "roles": set(), "lines": []})
            e["runs"].append(run_id)
            e["roles"] |= v["roles"]
            e["lines"] += [f"{run_id}: {line}" for line in v["lines"]]
    order = sorted(names)
    results = AxleChecker(cfg["axle"]).check_many([c for n in order for c in name_check_contents(n, opens_line)])
    for k, n in enumerate(order):
        bare, opened, namespace = results[3 * k: 3 * k + 3]
        e = names[n]
        e["roles"] = sorted(e["roles"])
        e["outage"] = any(r.status == OUTAGE for r in (bare, opened, namespace))
        ambiguous = any("Ambiguous term" in x for x in opened.errors)  # resolves to several existing constants
        e["exists"] = (("constant" if bare.status == OK else "constant under the items' opens" if opened.status == OK or ambiguous
                        else "namespace" if namespace.status == OK else None))
    real = {n: e for n, e in names.items() if not e["outage"]}
    absent = lambda role: sorted(n for n, e in real.items() if role in e["roles"] and not e["exists"])
    present = lambda role: sorted(n for n, e in real.items() if role in e["roles"] and e["exists"])
    totals = {"distinct_names": len(names), "outages": len(names) - len(real),
              "exist": sum(bool(e["exists"]) for e in real.values()), "n_absent": sum(not e["exists"] for e in real.values()),
              "absent": sorted(n for n, e in real.items() if not e["exists"])}
    for role in ("warned", "error_example", "recommended"):  # a name can have several roles
        totals[role] = {"names": sum(role in e["roles"] for e in real.values()), "n_absent": len(absent(role)),
                        "absent": absent(role), "exist": present(role)}
    only = {n: e for n, e in real.items() if e["roles"] == ["recommended"]}  # never warned against, never in an error example
    totals["only_recommended"] = {"names": len(only), "n_absent": sum(not e["exists"] for e in only.values()),
                                  "absent": sorted(n for n, e in only.items() if not e["exists"])}
    return {"note": "exploratory. Names in backtick spans and code blocks of runs/{B,D}_s*/best_prompt.txt; the role "
                    "comes from the clause around the name (src/chunk7.py prompt_names) and a name can have several.",
            "opens_tried": opens_line, "totals": totals, "names": names}


def compile_error_breakdown(cfg):
    rows = [r for arm in ("A", "B") for r in read_rows(ROOT / f"runs/final/{arm}.jsonl.gz")]
    items = {it["id"]: it for it in heldout_items("test", cfg)}
    return {"note": "exploratory", **compile_errors(rows, AxleChecker(cfg["axle"]), items)}


def check():
    w = ROOT / "writeup"
    entries = json.loads((w / "numbers.json").read_text())
    load = lambda s: json.loads((ROOT / s).read_text())
    numbers = {p.name: check_numbers(p.read_text(), entries, load) for p in [w / "writeup.md", *sorted(w.glob("email_*.md"))]}
    files = [p for p in [*w.glob("*.md"), ROOT / "README.md", ROOT / "LOG.md", *ROOT.glob("src/**/*.py"),
                         *ROOT.glob("scripts/*.py"), *ROOT.glob("tests/*.py")] if p.exists()]
    dashes = em_dashes(files)
    scan = subprocess.run([sys.executable, str(ROOT / "scripts/secret_scan.py"), "--history"], capture_output=True, text=True)
    out = {"numbers": numbers, "em_dashes": dashes, "files_scanned_for_em_dashes": len(files),
           "secret_scan_history": {"ok": scan.returncode == 0, "output": scan.stdout.strip().splitlines()[-1:]}}
    out["ok"] = all(n["ok"] for n in numbers.values()) and not dashes and out["secret_scan_history"]["ok"]
    return out


def main(argv):
    OUT.mkdir(parents=True, exist_ok=True)
    mode = argv[:1]
    if mode == ["candidate-truth"]:
        load_env()
        print(json.dumps(candidate_truth(load_config()), indent=1))
    elif mode == ["gap-slope"]:
        out = slopes(load_config())
        (OUT / "gap_slope.json").write_text(json.dumps(out, indent=1) + "\n")
        summary = json.loads((OUT / "candidate_truth_summary.json").read_text())
        figure(summary, ROOT / "figures/exploratory_judge_vs_truth_iterations.png", out)
        print(json.dumps(out, indent=1))
    elif mode == ["prompt-names"]:
        load_env()
        out = name_check(load_config())
        (OUT / "prompt_names.json").write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
        print(json.dumps(out["totals"], indent=1))
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
        cands = json.loads((OUT / "candidate_truth_summary.json").read_text())["runs"]
        for prefix in ("B", "D"):  # exploratory: GEPA's saved candidates, judge vs truth on the 70 validation items
            cs = [c for run_id, v in cands.items() if run_id.startswith(prefix) for c in v]
            out[f"candidates_{prefix}"] = {"candidates": len(cs), "judge_above_truth": sum(c["judge"] > c["truth"] for c in cs),
                                           "judge_equals_truth": sum(c["judge"] == c["truth"] for c in cs)}
        (OUT / "writeup_facts.json").write_text(json.dumps(out, indent=1) + "\n")
        print(json.dumps(out, indent=1))
    elif mode == ["seed-check"]:
        import pickle
        val = [it["id"] for it in gepa_items("val")]
        out = {"note": "exploratory"}
        for run_id in GEPA_RUNS:
            state = pickle.loads((ROOT / "runs" / run_id / "gepa/gepa_state.bin").read_bytes())
            gepa = state["prog_candidate_val_subscores"]
            files = dict(candidate_files(ROOT / "runs" / run_id))
            out[run_id] = {}
            for cand, rows in files.items():
                saved = {r["item_id"]: r["score"] for r in rows}
                out[run_id][cand] = sorted(val[k] for k, v in gepa[cand].items() if saved[val[k]] != v)
            out[run_id] = {"candidates_with_differences": {c: len(v) for c, v in out[run_id].items() if v},
                           "items": {c: v for c, v in out[run_id].items() if v}}
        (OUT / "seed_pass_check.json").write_text(json.dumps(out, indent=1) + "\n")
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
