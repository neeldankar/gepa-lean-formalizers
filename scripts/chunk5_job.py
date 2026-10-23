"""Chunk 5: the combined overnight job, started once inside `run_job.sh` on the pod.

Usage: python -m scripts.chunk5_job [--dry-run]
       python -m scripts.chunk5_job check           (session 2: invariants and health counts, no scores)
       python -m scripts.chunk5_job log-unmetered   (session 2: session 1's unmetered pod time as one gpu row)

Real run (chunk 5): the six GEPA runs in parallel (one subprocess each), one GPU meter for the pod,
then the sanity check, then the final eval of every arm on test and miniF2F into runs/final/.
`run_job.sh` then pushes the results and stops the pod. Any failure exits non-zero, and run_job.sh
still pushes the logs and stops the pod.

--dry-run (chunk 4): the same code path, small. Two GEPA runs (B_s0, D_s0) at about 10 metric calls
on 5 val items, written under runs/dryrun_chunk5/ so the real runs can never resume from them; then
the final eval of every arm on 5 TRAIN items standing in for test and miniF2F (rows labeled
dryrun_test / dryrun_minif2f). It never loads a test or miniF2F item.
"""
import copy
import json
import os
import subprocess
import sys
import time
from collections import Counter
from datetime import datetime, timezone

from src.axle_check import AxleChecker
from src.config import ROOT, load_config, load_env
from src.costs import GpuMeter
from src.data.firewall import gepa_items
from src.data.proofnet import read_jsonl
from src.final_eval import eval_arm, read_rows, write_rows
from src.generate import formalizer_client
from src.llm import BudgetExceeded, LLMClient
from src.scoring import memorization

DRY_RUNS = ("B_s0", "D_s0")
DRY_OVERRIDE = {"max_metric_calls": 10, "val_limit": 5}
DRY_ITEMS = 5


def job_plan(cfg, dry):
    """Everything that differs between the real job and its dry run."""
    if not dry:
        return {"chunk": 5, "runs_dir": "runs", "final_dir": "runs/final", "run_ids": list(cfg["gepa"]["runs"]),
                "override": {}, "standin_ids": None, "poll_seconds": 60}
    examples = set(cfg["fewshot"]["ids"])
    standins = [it["id"] for it in sorted(gepa_items("train"), key=lambda it: it["id"]) if it["id"] not in examples][:DRY_ITEMS]
    return {"chunk": 4, "runs_dir": "runs/dryrun_chunk5", "final_dir": "runs/dryrun_chunk5/final", "run_ids": list(DRY_RUNS),
            "override": DRY_OVERRIDE, "standin_ids": standins, "poll_seconds": 15}


def job_cfg(cfg, plan):
    """The config the final eval sees: in the dry run, arms B and D use only their one dry GEPA run."""
    cfg = copy.deepcopy(cfg)
    for run_id in plan["run_ids"]:
        cfg["gepa"]["runs"][run_id].update(plan["override"])
    if plan["standin_ids"] is not None:
        cfg["gepa"]["runs"] = {r: cfg["gepa"]["runs"][r] for r in plan["run_ids"]}
        for arm in cfg["arms"].values():
            if "gepa_runs" in arm:
                arm["gepa_runs"] = [r for r in arm["gepa_runs"] if r in plan["run_ids"]]
    return cfg


def standin_loader(plan):
    """items_for for eval_arm in the dry run: train items under dryrun_* labels; nothing held out."""
    ids = set(plan["standin_ids"])
    items = [it for it in gepa_items("train") if it["id"] in ids]
    return lambda dataset: (f"dryrun_{dataset}", items)


def sanity_check(cfg, runs_dir, run_ids):
    """Problems that must stop the job before the final eval ([] means it may go on)."""
    problems = []
    for run_id in run_ids:
        d = runs_dir / run_id
        spec = cfg["gepa"]["runs"][run_id]
        budget = spec.get("max_metric_calls", cfg["gepa"]["max_metric_calls"])
        val_size = spec.get("val_limit") or len(gepa_items("val"))
        if (d / "STOPPED").exists():
            problems.append(f"{run_id}: STOPPED ({(d / 'STOPPED').read_text().strip()[:200]})")
        if not (d / "DONE").exists():
            problems.append(f"{run_id}: no DONE marker")
            continue
        info = json.loads((d / "candidates.json").read_text())
        # GEPA checks its budget between iterations; one iteration is at most a minibatch of 3 plus a full val pass
        if info["total_metric_calls"] > budget + 3 + val_size:
            problems.append(f"{run_id}: {info['total_metric_calls']} metric calls for a budget of {budget}")
        if not (d / "best_prompt.txt").read_text().strip():
            problems.append(f"{run_id}: empty best prompt")
        if not list((d / "candidates").glob("*.jsonl")):
            problems.append(f"{run_id}: no saved candidate outputs")
    return problems


def run_gepa_children(cfg, plan, log_dir):
    """All GEPA runs in parallel, one subprocess each; one GPU meter here for the whole pod.
    A run that already has DONE is skipped ("skipped (done)"): on resume GEPA 0.1.4 re-evaluates the seed
    prompt on the full val set before it loads its saved state, so even a finished run would redo 70 items.
    The sanity check still checks skipped runs."""
    log_dir.mkdir(parents=True, exist_ok=True)
    runs_dir = ROOT / plan["runs_dir"]
    skipped = [r for r in plan["run_ids"] if (runs_dir / r / "DONE").exists()]
    children = {}
    for run_id in [r for r in plan["run_ids"] if r not in skipped]:
        cmd = [sys.executable, "-m", "scripts.gepa_run", run_id, "--chunk", str(plan["chunk"]), "--no-gpu-meter",
               "--runs-dir", plan["runs_dir"], "--override", json.dumps(plan["override"])]
        log = open(log_dir / f"{run_id}.log", "w")
        children[run_id] = (subprocess.Popen(cmd, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT), log)
    meter = GpuMeter(cfg, plan["chunk"], "chunk5_dryrun" if plan["standin_ids"] else "chunk5_job")
    try:
        while any(p.poll() is None for p, _ in children.values()):
            time.sleep(plan["poll_seconds"])
            meter.tick()
        meter.tick()
    except BudgetExceeded:
        for p, _ in children.values():
            p.terminate()
        raise
    finally:
        for _, log in children.values():
            log.close()
    return {**{run_id: "skipped (done)" for run_id in skipped}, **{run_id: p.returncode for run_id, (p, _) in children.items()}}


def push(message, run=subprocess.run):
    """Commit runs/ and push, the way run_job.sh does; the token is never printed. Returns a status string."""
    load_env()
    remote = f"https://x-access-token:{os.environ['GITHUB_TOKEN']}@github.com/neeldankar/gepa-lean-formalizers.git"
    run(["git", "add", "runs/"], cwd=ROOT)
    run(["git", "commit", "-q", "-m", message], cwd=ROOT)
    run(["git", "pull", "-q", "--rebase", remote, "main"], cwd=ROOT, capture_output=True)
    if run([sys.executable, "scripts/secret_scan.py", "--history"], cwd=ROOT).returncode != 0:
        return "secret scan failed; not pushed"
    return "pushed" if run(["git", "push", "-q", remote, "HEAD:main"], cwd=ROOT, capture_output=True).returncode == 0 else "push failed"


def final_order(cfg):
    """Every arm, with the arms that call an outside API per item (missing_on_api_failure: arm F) last."""
    return sorted(cfg["arms"], key=lambda a: bool(cfg["arms"][a].get("missing_on_api_failure")))


def run_final(cfg, plan, runs_dir, final_dir, save, push=push):
    """Final eval of every arm. An API call that exhausted its retries (LLMError) or any other error is
    returned as `error` so the job records it and exits non-zero; arms finished before it are kept.
    Deviation 3: arm F runs last, after the other arms are written and pushed (not in the dry run); its
    failed calls are missing rows, counted here, not errors."""
    dry = plan["standin_ids"] is not None
    checker = AxleChecker(cfg["axle"])
    judge = LLMClient(cfg, plan["chunk"], run_id="final" if not dry else "chunk5_dryrun_final")
    index = memorization.load_index()
    items_for = standin_loader(plan) if dry else None
    rows_per_arm, outages, pushed = {}, 0, False
    for arm in final_order(cfg):
        if cfg["arms"][arm].get("missing_on_api_failure") and not pushed:
            pushed = True
            if not dry:
                try:
                    status = push("Results: chunk 5 final eval, every arm but " + arm)
                except Exception as e:  # arm F still runs; run_job.sh pushes again at the end
                    status = f"push error: {type(e).__name__}: {e}"[:300]
                print(f"before arm {arm}: {status}", flush=True)
                save(push_before_last_arms=status)
        try:
            gen = formalizer_client(cfg, cfg["arms"][arm]["model"], plan["chunk"],
                                    run_id=f"final_{arm}" if not dry else f"chunk5_dryrun_{arm}")
            rows = eval_arm(cfg, arm, gen, judge, checker, runs_dir, ROOT, mem_index=index, items_for=items_for)
        except Exception as e:
            return rows_per_arm, outages, f"arm {arm}: {type(e).__name__}: {e}"[:1000]
        write_rows(final_dir / f"{arm}.jsonl.gz", rows)
        rows_per_arm[arm] = {"rows": len(rows), "datasets": sorted({r["dataset"] for r in rows}),
                             "missing_generation": sum(bool(r.get("generation_missing")) for r in rows),
                             "item_ids": sorted({r["item_id"] for r in rows}) if dry else None}
        outages += sum(r["outage"] for r in rows)
        print(f"arm {arm}: {len(rows)} rows", flush=True)
        save(final=rows_per_arm)
    return rows_per_arm, outages, None


def expected_ids(root=ROOT):
    """{dataset: set of ids} every final-eval run must cover: the 247 test items and the usable miniF2F items."""
    return {"test": set(json.loads((root / "data/splits.json").read_text())["test"]),
            "minif2f": {it["id"] for it in read_jsonl(root / "data/minif2f.jsonl")}}


def coverage_problems(cfg, arm, rows, expected):
    """Each of the arm's runs (one, or one per GEPA seed) has exactly the expected ids in each of its datasets."""
    spec = cfg["arms"][arm]
    datasets = ["test"] if spec.get("test_only") else ["test", "minif2f"]
    problems = []
    for run_id in spec.get("gepa_runs", [None]):
        got = {}
        for r in rows:
            if r["run_id"] == run_id:
                got.setdefault(r["dataset"], set()).add(r["item_id"])
        for ds in sorted(set(got) - set(datasets)):
            problems.append(f"{arm} {run_id}: unexpected dataset {ds} ({len(got[ds])} items)")
        for ds in datasets:
            ids = got.get(ds, set())
            if ids != expected[ds]:
                problems.append(f"{arm} {run_id} {ds}: {len(expected[ds] - ids)} missing, {len(ids - expected[ds])} extra ids")
    stray = {r["run_id"] for r in rows} - set(spec.get("gepa_runs", [None]))
    if stray:
        problems.append(f"{arm}: rows from unexpected runs {sorted(map(str, stray))}")
    return problems


def duplicate_keys(rows):
    """How many rows repeat an (arm, run_id, dataset, item_id, sample) key."""
    keys = Counter((r["arm"], r["run_id"], r["dataset"], r["item_id"], r["sample"]) for r in rows)
    return sum(n - 1 for n in keys.values())


def invariant_violations(rows):
    """Rows scored faithful (or certified) without compiling. Row by row, so no faithful count is ever formed."""
    return {"judge_faithful_not_compiled": sum(r["judge_score"] == 1 and not r["compiled"] for r in rows),
            "truth_faithful_not_compiled": sum(r["truth_label"] == "faithful" and not r["compiled"] for r in rows),
            "certified_not_compiled": sum(bool(r["certified"]) and not r["compiled"] for r in rows)}


def health_counts(rows, samples):
    """Counts only: no judge, truth, certificate or memorization numbers."""
    scored = [r for r in rows if not r["generation_missing"]]
    return {
        "rows": len(rows),
        "bad_sample_index": sum(not 0 <= r["sample"] < samples for r in rows),
        "format_failure": sum(bool(r["format_failure"]) for r in scored),
        "compile_failure_incl_format": sum(not r["compiled"] for r in scored),
        "compile_failure_excl_format": sum(not r["compiled"] and not r["format_failure"] for r in scored),
        "compile_status_failures": dict(sorted(Counter(r["compile_status"] for r in scored
                                                       if r["compile_status"] not in ("ok", None)).items())),
        "outage": sum(bool(r["outage"]) for r in rows),
        "judge_missing": sum(bool(r["judge_missing"]) for r in rows),
        "ref_missing": sum(bool(r["ref_missing"]) for r in rows),
        "truth_missing": dict(sorted(Counter(r["truth_source"] for r in scored if r["truth_label"] is None).items())),
        "generation_missing": sum(bool(r["generation_missing"]) for r in rows),
    }


def arm_health(cfg, arm, rows, expected):
    out = {"coverage_problems": coverage_problems(cfg, arm, rows, expected), "duplicate_keys": duplicate_keys(rows),
           "violations": invariant_violations(rows), "counts": health_counts(rows, cfg["generation"]["samples"])}
    if "gepa_runs" in cfg["arms"][arm]:
        out["counts_per_run"] = {r: health_counts([x for x in rows if x["run_id"] == r], cfg["generation"]["samples"])
                                 for r in cfg["arms"][arm]["gepa_runs"]}
    out["pass"] = (not out["coverage_problems"] and not out["duplicate_keys"] and not any(out["violations"].values())
                   and not out["counts"]["outage"] and not out["counts"]["generation_missing"]
                   and not out["counts"]["bad_sample_index"])
    return out


def budget_report(cfg, runs_dir, run_ids):
    """Each run's GEPA metric calls against its budget; the limit is sanity_check's (one iteration over)."""
    val_size = len(gepa_items("val"))
    runs = {}
    for run_id in run_ids:
        d = runs_dir / run_id
        budget = cfg["gepa"]["runs"][run_id].get("max_metric_calls", cfg["gepa"]["max_metric_calls"])
        total = json.loads((d / "candidates.json").read_text())["total_metric_calls"] if (d / "DONE").exists() else None
        runs[run_id] = {"total_metric_calls": total, "budget": budget, "limit": budget + 3 + val_size,
                        "over_budget_by": None if total is None else max(0, total - budget),
                        "done": (d / "DONE").exists(), "stopped": (d / "STOPPED").exists()}
    return {"runs": runs, "problems": sanity_check(cfg, runs_dir, run_ids)}


def health_check(cfg, runs_dir, final_dir, root=ROOT):
    expected = expected_ids(root)
    out = {"time": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "expected_items": {ds: len(ids) for ds, ids in expected.items()},
           "gepa_budget": budget_report(cfg, runs_dir, list(cfg["gepa"]["runs"])), "arms": {}}
    for arm in cfg["arms"]:
        path = final_dir / f"{arm}.jsonl.gz"
        out["arms"][arm] = arm_health(cfg, arm, read_rows(path), expected) if path.exists() else {"pass": False, "missing_file": str(path)}
    out["pass"] = not out["gepa_budget"]["problems"] and all(a["pass"] for a in out["arms"].values())
    return out


def log_unmetered(cfg, costs_path=ROOT / "runs/costs.jsonl", health_path=ROOT / "runs/chunk5_launch_health.json"):
    """Session 1's unmetered pod time (setup and the gap before the relaunch) as one balancing gpu row, once."""
    rows = read_jsonl(costs_path)
    if any(r.get("run_id") == "pod_unmetered_session1" for r in rows):
        return None
    hours = json.loads(health_path.read_text())["unmetered_pod_time"]["unmetered_hours"]
    row = {"time": "2026-10-22T06:37:03+00:00", "chunk": 5, "run_id": "pod_unmetered_session1", "purpose": "gpu",
           "model": "pod", "prompt_tokens": 0, "completion_tokens": 0, "usd": hours * cfg["gpu"]["usd_per_hour"],
           "hours": hours}
    with open(costs_path, "a") as f:
        f.write(json.dumps(row) + "\n")
    return row


def main(argv):
    if argv[:1] == ["check"]:
        out = health_check(load_config(), ROOT / "runs", ROOT / "runs/final")
        (ROOT / "runs/chunk5_health.json").write_text(json.dumps(out, indent=1) + "\n")
        print("PASS" if out["pass"] else "FAIL")
        sys.exit(0 if out["pass"] else 1)
    if argv[:1] == ["log-unmetered"]:
        print(log_unmetered(load_config()))
        return
    dry = "--dry-run" in argv
    cfg = load_config()
    plan = job_plan(cfg, dry)
    cfg = job_cfg(cfg, plan)
    runs_dir, final_dir = ROOT / plan["runs_dir"], ROOT / plan["final_dir"]
    runs_dir.mkdir(parents=True, exist_ok=True)
    summary = {"dry_run": dry, "plan": plan, "started": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    path = runs_dir / "job_summary.json"

    def save(**kw):
        summary.update(kw)
        path.write_text(json.dumps(summary, indent=1) + "\n")

    save()
    print("GEPA runs:", plan["run_ids"], flush=True)
    try:
        save(gepa_exit_codes=run_gepa_children(cfg, plan, runs_dir / "logs"))
    except BudgetExceeded as e:
        save(stopped=f"budget: {e}")
        sys.exit(2)
    problems = sanity_check(cfg, runs_dir, plan["run_ids"])
    save(sanity_problems=problems)
    if problems:
        print("sanity check failed:", *problems, sep="\n  ", flush=True)
        sys.exit(1)
    print("sanity check passed", flush=True)

    rows_per_arm, outages, error = run_final(cfg, plan, runs_dir, final_dir, save)
    if error:
        save(final_error=error)
        print("final eval failed:", error, flush=True)
        sys.exit(1)
    save(outages=outages, finished=datetime.now(timezone.utc).isoformat(timespec="seconds"))
    sys.exit(1 if outages else 0)


if __name__ == "__main__":
    main(sys.argv[1:])
