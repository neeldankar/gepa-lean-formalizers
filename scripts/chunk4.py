"""Chunk 4: the pilot (prereg "Pilot and go criteria"). Validation items only.

Steps (write into runs/chunk4/ and summary.json there):
  gen      (pod) 30 seeded val items, three configurations: Qwen3-8B thinking off and on (arm A's
           prompt), ReForm-8B (arm C's prompt). Generation is timed on its own, then every output
           gets the judge score, the truth score and the memorization check.
  armf     (pod) arm F's model on the first 10 pilot items: generation only, for cost per item.
  label    (pod) the blind labeling page for 20 compiled outputs, mapping kept in label_sample.jsonl.
  gepa     (pod) the short GEPA run (config pilot.gepa_run), thinking mode from --thinking on|off.
  gpu      pod GPU cost: wall clock since the container started (or --until ISO time) times the
           hourly rate, minus GPU hours already logged for chunk 4, appended as one balancing row.
  agree    reference judge (and optimization judge) agreement with Neel's labels (--labels path).
  project  projected cost of the full study from the pilot's measurements.
  costs    chunk 4 costs from runs/costs.jsonl.
`report` prints the LOG.md lines, the go/no-go table and 5 random raw pilot examples.
"""
import copy
import csv
import json
import random
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from src.axle_check import AxleChecker
from src.config import ROOT, load_config
from src.costs import summarize
from src.data.firewall import gepa_items
from src.data.proofnet import read_jsonl, write_jsonl
from src.final_eval import read_rows, score_row, write_rows
from src.generate import formalizer_client, generate
from src.llm import COSTS_PATH, LLMClient
from src.prompting import load_instructions
from src.scoring import memorization
from src.scoring.labeling import build_page
from src.scoring.normalize import normalize_statement

CHUNK = 4
RUN_DIR = ROOT / "runs/chunk4"
SUMMARY = RUN_DIR / "summary.json"
PILOT = RUN_DIR / "pilot.jsonl.gz"
# name: (model key, prompt, enable_thinking or None)
CONFIGS = {
    "qwen_nothink": ("qwen3-8b", "prompts/arm_A.txt", False),
    "qwen_think": ("qwen3-8b", "prompts/arm_A.txt", True),
    "reform": ("reform-8b", "prompts/arm_C.txt", None),
}
QWEN_PROMPTS, REFORM_PROMPTS = 5, 4  # final eval: A, B x3, E on Qwen3-8B; C, D x3 on ReForm-8B


def load_summary():
    return json.loads(SUMMARY.read_text()) if SUMMARY.exists() else {}


def save_summary(summary):
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    SUMMARY.write_text(json.dumps(summary, indent=1, ensure_ascii=False) + "\n")


def pilot_items(cfg):
    """The seeded pilot subset of the validation split (never test or miniF2F)."""
    val = sorted(gepa_items("val"), key=lambda it: it["id"])
    return random.Random(cfg["pilot"]["seed"]).sample(val, cfg["pilot"]["val_items"])


def config_cfg(cfg, name):
    model_key, _, thinking = CONFIGS[name]
    c = copy.deepcopy(cfg)
    if thinking is not None:
        c["models"][model_key]["enable_thinking"] = thinking
    return c


def container_start():
    """Start time of the pod's container (PID 1), UTC."""
    out = subprocess.run(["ps", "-o", "lstart=", "-p", "1"], capture_output=True, text=True, check=True).stdout
    return datetime.strptime(" ".join(out.split()), "%a %b %d %H:%M:%S %Y").replace(tzinfo=timezone.utc)


def gpu_balance(cfg, start, until, costs_path=COSTS_PATH, chunk=CHUNK):
    """Append one `gpu` row so chunk GPU hours equal the pod's wall clock since `start`."""
    rows = read_jsonl(costs_path) if costs_path.exists() else []
    logged = sum(r.get("hours", 0) for r in rows if r["chunk"] == chunk and r["purpose"] == "gpu")
    hours = max(0.0, (until - start).total_seconds() / 3600 - logged)
    row = {"time": until.isoformat(timespec="seconds"), "chunk": chunk, "run_id": "pod_session", "purpose": "gpu",
           "model": "pod", "prompt_tokens": 0, "completion_tokens": 0, "usd": hours * cfg["gpu"]["usd_per_hour"],
           "hours": hours}
    with open(costs_path, "a") as f:
        f.write(json.dumps(row) + "\n")
    return {"logged_hours_before": logged, "added_hours": hours, "total_hours": logged + hours,
            "total_usd": (logged + hours) * cfg["gpu"]["usd_per_hour"]}


def gpu(cfg, summary, argv=()):
    start = datetime.fromisoformat(summary["pod"]["container_start"])
    until = datetime.fromisoformat(argv[argv.index("--until") + 1]) if "--until" in argv else datetime.now(timezone.utc)
    summary.setdefault("gpu_balances", []).append({"until": until.isoformat(), **gpu_balance(cfg, start, until)})


def setup_hours(venv="/workspace/venv", log="/workspace/setup.log"):
    """Pod setup time: from the venv's creation (setup_pod.sh's first act) to setup.log's last write."""
    born = int(subprocess.run(["stat", "-c", "%W", venv], capture_output=True, text=True, check=True).stdout)
    done = int(subprocess.run(["stat", "-c", "%Y", log], capture_output=True, text=True, check=True).stdout)
    return (done - born) / 3600


def gen(cfg, summary, argv=()):
    summary["pod"] = {"container_start": container_start().isoformat(), "gpu_type": cfg["gpu"]["type"],
                      "usd_per_hour": cfg["gpu"]["usd_per_hour"]}
    summary["setup_hours"] = setup_hours()
    gpu(cfg, summary)
    items = pilot_items(cfg)
    checker = AxleChecker(cfg["axle"])
    workers = cfg["generation"]["workers"]
    # A rerun finds earlier generations in the cache, so a configuration is timed only once: its timing
    # is saved as soon as it is measured, or read back from an earlier run's log (--timing-log).
    timing = summary.setdefault("gen_timing", {})
    if "--timing-log" in argv:
        for line in open(argv[argv.index("--timing-log") + 1]):
            name, _, rest = line.strip().partition(" ")
            if name in CONFIGS and rest.startswith("{"):
                timing[name] = {**json.loads(rest), "source": "earlier run's log"}
    rows = []
    for name, (model_key, prompt, _) in CONFIGS.items():
        c = config_cfg(cfg, name)
        instructions = load_instructions(prompt)
        genc = formalizer_client(c, model_key, CHUNK, run_id=f"pilot_{name}")
        judge = LLMClient(c, CHUNK, run_id=f"pilot_{name}")
        if name not in timing:
            t0 = time.monotonic()  # generation alone, all items at `workers` concurrency
            with ThreadPoolExecutor(workers) as pool:
                outs = list(pool.map(lambda it: generate(genc, c, model_key, instructions, it), items))
            seconds = time.monotonic() - t0
            tokens = sum((o.get("usage") or {}).get("completion_tokens") or 0 for o in outs)
            timing[name] = {"items": len(items), "gen_seconds": seconds, "completion_tokens": tokens,
                            "tokens_per_second": tokens / seconds if seconds else None, "workers": workers}
            save_summary(summary)
        with ThreadPoolExecutor(workers) as pool:  # generations now come from the cache
            rs = list(pool.map(lambda it: score_row(c, name, model_key, None, None, "val", instructions, it, 0,
                                                    genc, judge, checker), items))
        statements = [r["normalized"] for r in rs if r["normalized"]]
        matched = memorization.exact_matches(checker, memorization.load_index(),
                                             [it for it, r in zip(items, rs) if r["normalized"]], statements)
        for r, m in zip([r for r in rs if r["normalized"]], matched):
            r["memorized"] = m
        for r in rs:
            r["config"], r["model"] = name, model_key
        rows += rs
        print(name, json.dumps(timing[name]))
    write_rows(PILOT, rows)
    summary["gen"] = {"item_ids": [it["id"] for it in items], "timing": timing}
    gpu(cfg, summary)


def armf(cfg, summary, argv=()):
    items = pilot_items(cfg)[: cfg["pilot"]["arm_f_items"]]
    genc = formalizer_client(cfg, "arm_f", CHUNK, run_id="pilot_arm_f")
    instructions = load_instructions(cfg["arms"]["F"]["prompt"])
    with ThreadPoolExecutor(cfg["generation"]["workers"]) as pool:
        outs = list(pool.map(lambda it: generate(genc, cfg, "arm_f", instructions, it), items))
    rows = [{"item_id": it["id"], "output": o["text"], "finish_reason": o["finish_reason"], "usage": o.get("usage")}
            for it, o in zip(items, outs)]
    write_jsonl(RUN_DIR / "arm_f.jsonl", rows)
    summary["armf"] = {"model": cfg["models"]["arm_f"]["served_name"], "items": len(rows),
                       "finish_reasons": dict(sorted({r["finish_reason"]: sum(x["finish_reason"] == r["finish_reason"] for x in rows) for r in rows}.items()))}


def pick_label_rows(rows, cfg):
    """20 compiled outputs on distinct items: 5 per Qwen3-8B mode and 10 ReForm-8B, then shuffled."""
    rng = random.Random(cfg["pilot"]["seed"])
    n = cfg["pilot"]["label_items"]
    quota = {"qwen_nothink": n // 4, "qwen_think": n // 4, "reform": n - 2 * (n // 4)}
    used, picked = set(), []
    for name, k in quota.items():
        pool = [r for r in rows if r["config"] == name and r["compiled"] and r["ref_verdict"] and r["item_id"] not in used]
        rng.shuffle(pool)
        for r in pool[:k]:
            picked.append(r)
            used.add(r["item_id"])
    rng.shuffle(picked)
    return picked


def label_records(picked, items):
    """(hidden mapping, page records). Page records carry no arm, model or configuration."""
    mapping, records = [], []
    for k, r in enumerate(picked, 1):
        label_id = f"P{k:02d}"
        it = items[r["item_id"]]
        mapping.append({"label_id": label_id, "config": r["config"], "item_id": r["item_id"]})
        records.append({"label_id": label_id, "english": it["informal_stmt"],
                        "reference": normalize_statement(it["formal_stmt"]), "candidate": r["normalized"]})
    return mapping, records


def label(cfg, summary, argv=()):
    items = {it["id"]: it for it in gepa_items("val")}
    mapping, records = label_records(pick_label_rows(read_rows(PILOT), cfg), items)
    write_jsonl(RUN_DIR / "label_sample.jsonl", mapping)
    client = LLMClient(cfg, CHUNK, run_id="pilot_label")
    build_page(client, cfg, records, RUN_DIR / "labeling.html", page_key="chunk4-pilot")
    summary["label"] = {"n": len(mapping), "by_config": {c: sum(m["config"] == c for m in mapping) for c in CONFIGS}}


def agreement(rows, mapping, labels):
    """Agreement of the reference judge, the truth label and the optimization judge with hand labels.
    `agree` counts out of all labeled items (an unsure label never agrees); `n_decided` excludes unsure."""
    by_key = {(r["config"], r["item_id"]): r for r in rows}
    out = {"n": len(mapping), "unsure": 0, "missing": 0}
    counts = {"ref_judge": 0, "truth_label": 0, "opt_judge": 0}
    per = []
    for m in mapping:
        lab = labels.get(m["label_id"], "")
        r = by_key[(m["config"], m["item_id"])]
        verdicts = {"ref_judge": r["ref_verdict"], "truth_label": r["truth_label"], "opt_judge": r["judge_verdict"]}
        if lab == "unsure":
            out["unsure"] += 1
        elif lab not in ("faithful", "unfaithful"):
            out["missing"] += 1
        else:
            for k, v in verdicts.items():
                counts[k] += v == lab
        per.append({**m, "label": lab, **verdicts, "certified": r["certified"]})
    out["n_decided"] = out["n"] - out["unsure"] - out["missing"]
    out.update({k: {"agree": v, "of": out["n"]} for k, v in counts.items()})
    return out, per


def agree(cfg, summary, argv=()):
    path = argv[argv.index("--labels") + 1] if "--labels" in argv else RUN_DIR / "labels.csv"
    with open(path) as f:
        labels = {r["label_id"]: r["label"] for r in csv.DictReader(f)}
    out, per = agreement(read_rows(PILOT), read_jsonl(RUN_DIR / "label_sample.jsonl"), labels)
    write_jsonl(RUN_DIR / "agreement.jsonl", per)
    summary["agree"] = out


def config_stats(rows, costs_rows, name):
    rs = [r for r in rows if r["config"] == name and not r["outage"]]
    toks = sorted(r["completion_tokens"] or 0 for r in rs)
    api = sum(c["usd"] for c in costs_rows if c.get("run_id") == f"pilot_{name}")
    return {
        "outputs": len(rs),
        "compile_rate": 100 * sum(r["compiled"] for r in rs) / len(rs),
        "format_failures": sum(r["format_failure"] for r in rs),
        "truth_faithful_rate": 100 * sum(r["truth_label"] == "faithful" for r in rs) / len(rs),
        "judge_score_rate": 100 * sum(r["judge_score"] or 0 for r in rs) / len(rs),
        "certified": sum(r["certified"] for r in rs),
        "exact_match_rate": 100 * sum(bool(r["memorized"]) for r in rs) / len(rs),
        "hit_length_cap": sum(r["finish_reason"] == "length" for r in rs),
        "tokens_mean": sum(toks) / len(toks), "tokens_median": toks[len(toks) // 2], "tokens_max": toks[-1],
        "api_usd_per_output": api / len(rs),
        "outages": sum(1 for r in rows if r["config"] == name and r["outage"]),
    }


def projection(m, cfg):
    """Projected full-study cost (USD) from pilot measurements `m`:
    gen_s_per_item {qwen, reform} (GPU seconds per item at pilot concurrency), api_per_output {qwen,
    reform}, gepa_gpu_s_per_call and gepa_api_per_call (Qwen3-8B pilot run), armf_usd_per_item,
    gloss_usd, setup_hours, spent_usd (all chunks so far)."""
    rate = cfg["gpu"]["usd_per_hour"]
    budget = cfg["gepa"]["max_metric_calls"]
    n_items = cfg["split"]["test"] + m["minif2f_items"]
    reform_ratio = m["gen_s_per_item"]["reform"] / m["gen_s_per_item"]["qwen"]
    gepa_qwen_h = budget * m["gepa_gpu_s_per_call"] / 3600
    gepa_reform_h = gepa_qwen_h * reform_ratio
    gepa_gpu_serial = 3 * (gepa_qwen_h + gepa_reform_h) * rate
    gepa_gpu_parallel = max(gepa_qwen_h, gepa_reform_h) * rate  # six runs at once share the GPU
    gepa_api = 6 * budget * m["gepa_api_per_call"]
    eval_h = n_items * (QWEN_PROMPTS * m["gen_s_per_item"]["qwen"] + REFORM_PROMPTS * m["gen_s_per_item"]["reform"]) / 3600
    eval_api = n_items * (QWEN_PROMPTS * m["api_per_output"]["qwen"] + REFORM_PROMPTS * m["api_per_output"]["reform"])
    armf = cfg["split"]["test"] * (m["armf_usd_per_item"] + m["api_per_output"]["qwen"])
    handcheck = 100 * 2 * m["gloss_usd"]
    chunk5_serial = gepa_gpu_serial + gepa_api + (eval_h + m["setup_hours"]) * rate + eval_api + armf
    chunk5_parallel = gepa_gpu_parallel + gepa_api + (eval_h + m["setup_hours"]) * rate + eval_api + armf
    later = cfg["budget"]["chunk_caps_usd"][6] + cfg["budget"]["chunk_caps_usd"][7]  # upper bound for chunks 6 and 7
    return {
        "gepa_gpu_usd_serial": gepa_gpu_serial, "gepa_gpu_usd_parallel": gepa_gpu_parallel, "gepa_api_usd": gepa_api,
        "final_eval_gpu_hours": eval_h, "final_eval_gpu_usd": eval_h * rate, "final_eval_api_usd": eval_api,
        "arm_f_usd": armf, "setup_gpu_usd": m["setup_hours"] * rate, "handcheck_gloss_usd": handcheck,
        "chunk5_usd_serial": chunk5_serial, "chunk5_usd_parallel": chunk5_parallel,
        "chunks6_7_cap_usd": later, "spent_usd": m["spent_usd"],
        "total_usd_upper": m["spent_usd"] + chunk5_serial + later,
        "total_usd_parallel": m["spent_usd"] + chunk5_parallel + later,
    }


def go_checks(qwen_truth_rate, ref_agree, exact_match_rates, projected_total):
    """The four go criteria from prereg "Pilot and go criteria"."""
    return [
        {"check": "Qwen3-8B truth-faithful rate between about 10% and 70%", "value": qwen_truth_rate,
         "go": 10 <= qwen_truth_rate <= 70},
        {"check": "reference judge agrees with Neel on at least 16 of 20", "value": ref_agree, "go": ref_agree >= 16},
        {"check": "exact matches with known ProofNet statements under about 20% (every configuration)",
         "value": max(exact_match_rates.values()), "go": max(exact_match_rates.values()) < 20},
        {"check": "projected total under $300", "value": projected_total, "go": projected_total < 300},
    ]


def gepa(cfg, summary, argv=()):
    from scripts import gepa_run
    p = cfg["pilot"]
    spec = dict(p["gepa_run"])
    if "--thinking" in argv:
        spec["enable_thinking"] = argv[argv.index("--thinking") + 1] == "on"
    cfg["gepa"]["runs"] = {p["gepa_run_id"]: spec}
    summary["gepa_launch"] = {"run_id": p["gepa_run_id"], **spec,
                              "started": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    save_summary(summary)
    gepa_run.run(cfg, p["gepa_run_id"], CHUNK)


def costs(cfg, summary, argv=()):
    summary["costs"] = summarize([r for r in read_jsonl(COSTS_PATH) if r["chunk"] == CHUNK])
    summary["costs_all_chunks_usd"] = sum(r["usd"] for r in read_jsonl(COSTS_PATH))


def project(cfg, summary, argv=()):
    rows = read_rows(PILOT)
    crow = read_jsonl(COSTS_PATH)
    stats = {name: config_stats(rows, crow, name) for name in CONFIGS}
    t = summary["gen"]["timing"]
    run_id = summary["gepa_launch"]["run_id"]
    qcfg = "qwen_think" if summary["gepa_launch"]["enable_thinking"] else "qwen_nothink"
    cand = json.loads((ROOT / "runs" / run_id / "candidates.json").read_text())
    calls = cand["total_metric_calls"]
    gepa_rows = [c for c in crow if c.get("run_id") == run_id]
    gepa_hours = sum(c.get("hours", 0) for c in gepa_rows if c["purpose"] == "gpu")
    gepa_api = sum(c["usd"] for c in gepa_rows if c["purpose"] != "gpu")
    gloss = [c for c in crow if c.get("run_id") == "pilot_label"]
    armf_rows = [c for c in crow if c.get("run_id") == "pilot_arm_f"]
    m = {
        "minif2f_items": len(read_jsonl(ROOT / "data/minif2f.jsonl")),
        "gen_s_per_item": {"qwen": t[qcfg]["gen_seconds"] / t[qcfg]["items"],
                           "reform": t["reform"]["gen_seconds"] / t["reform"]["items"]},
        "api_per_output": {"qwen": stats[qcfg]["api_usd_per_output"], "reform": stats["reform"]["api_usd_per_output"]},
        "gepa_gpu_s_per_call": gepa_hours * 3600 / calls, "gepa_api_per_call": gepa_api / calls,
        "armf_usd_per_item": sum(c["usd"] for c in armf_rows) / len(armf_rows) if armf_rows else 0.0,
        "gloss_usd": sum(c["usd"] for c in gloss) / len(gloss) if gloss else 0.0,
        "setup_hours": summary["setup_hours"], "spent_usd": sum(c["usd"] for c in crow),
    }
    proj = projection(m, cfg)
    vals = cand["val_aggregate_scores"]
    summary["stats"] = stats
    summary["gepa_pilot"] = {"run_id": run_id, "config": qcfg, "metric_calls": calls, "candidates": len(vals),
                             "seed_val": vals[0], "best_val": max(vals), "reflection_calls": cand["reflection_calls"],
                             "gpu_hours": gepa_hours, "api_usd": gepa_api}
    summary["measurements"] = m
    summary["projection"] = proj
    ref_agree = summary["agree"]["ref_judge"]["agree"] if "agree" in summary else None
    summary["go"] = go_checks(stats[qcfg]["truth_faithful_rate"], ref_agree if ref_agree is not None else -1,
                              {k: v["exact_match_rate"] for k, v in stats.items()}, proj["total_usd_upper"])


STEPS = {"gen": gen, "armf": armf, "label": label, "gepa": gepa, "gpu": gpu, "agree": agree,
         "costs": costs, "project": project}


def report():
    s = load_summary()
    print(f"- Pod: {s['pod']['gpu_type']} at ${s['pod']['usd_per_hour']}/hr; container start {s['pod']['container_start']}")
    for name, t in s["gen"]["timing"].items():
        st = s["stats"][name]
        print(f"- {name}: {st['outputs']} outputs; compile {st['compile_rate']:.1f}%; format failures {st['format_failures']}; "
              f"truth faithful {st['truth_faithful_rate']:.1f}%; judge score {st['judge_score_rate']:.1f}%; certified {st['certified']}; "
              f"exact matches {st['exact_match_rate']:.1f}%; tokens mean {st['tokens_mean']:.0f}, median {st['tokens_median']}, "
              f"max {st['tokens_max']}; hit cap {st['hit_length_cap']}; {t['tokens_per_second']:.0f} tokens/s at {t['workers']} workers; "
              f"{t['gen_seconds'] / t['items']:.1f} GPU s/item; API ${st['api_usd_per_output']:.5f}/output; outages {st['outages']}")
    if "agree" in s:
        a = s["agree"]
        print(f"- Hand labels: {a['n']} items, {a['unsure']} unsure, {a['missing']} missing; reference judge "
              f"{a['ref_judge']['agree']}/{a['n']}, truth label {a['truth_label']['agree']}/{a['n']}, "
              f"optimization judge {a['opt_judge']['agree']}/{a['n']}")
    g = s["gepa_pilot"]
    print(f"- GEPA pilot {g['run_id']} ({g['config']}): {g['metric_calls']} metric calls, {g['candidates']} candidates, "
          f"val score seed {g['seed_val']:.3f} -> best {g['best_val']:.3f}; {g['reflection_calls']} reflection calls; "
          f"GPU {g['gpu_hours']:.2f} h; API ${g['api_usd']:.3f}")
    m = s["measurements"]
    print(f"- Per metric call: {m['gepa_gpu_s_per_call']:.1f} GPU s, API ${m['gepa_api_per_call']:.5f}")
    print("- Projection (USD): " + ", ".join(f"{k} {v:.2f}" for k, v in s["projection"].items()))
    print("\n| Go check | Value | Go |\n| --- | --- | --- |")
    for c in s["go"]:
        print(f"| {c['check']} | {c['value']:.1f} | {'yes' if c['go'] else 'NO'} |")
    c = s["costs"]
    print(f"\n- Chunk 4 cost: ${c['usd_total']:.2f}; by purpose: "
          + ", ".join(f"{k} {v['calls']} rows ${v['usd']:.3f}" for k, v in c["by_purpose"].items()))
    print("\n5 random pilot rows (seed 0):")
    for r in random.Random(0).sample(read_rows(PILOT), 5):
        print(f"\n[{r['config']} | {r['item_id']} | compiled {r['compiled']} | judge {r['judge_verdict']} -> score {r['judge_score']} "
              f"| ref judge {r['ref_verdict']} | certified {r['certified']} | truth {r['truth_label']} | tokens {r['completion_tokens']}]")
        print("output tail:", r["output"][-400:].replace("\n", " "))
        print("normalized:", r["normalized"])


def main():
    if sys.argv[1:] == ["report"]:
        return report()
    cfg = load_config()
    summary = load_summary()
    name, argv = sys.argv[1], sys.argv[2:]
    print(f"== {name}")
    try:
        STEPS[name](cfg, summary, argv)
    finally:
        save_summary(summary)


if __name__ == "__main__":
    main()
