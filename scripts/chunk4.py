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
import hashlib
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
from src.prompting import context_block, load_fewshot, load_instructions, user_message
from src.scoring import memorization
from src.scoring.labeling import build_page
from src.scoring.normalize import normalize_statement

CHUNK = 4
RUN_DIR = ROOT / "runs/chunk4"
SUMMARY = RUN_DIR / "summary.json"
PILOT = RUN_DIR / "pilot.jsonl.gz"
PILOT_A2 = RUN_DIR / "pilot_a2.jsonl.gz"
# name: (model key, prompt, enable_thinking or None)
CONFIGS = {
    "qwen_nothink": ("qwen3-8b", "prompts/arm_A.txt", False),
    "qwen_think": ("qwen3-8b", "prompts/arm_A.txt", True),
    "reform": ("reform-8b", "prompts/arm_C.txt", None),
}
# The rerun after the first go check: Neel's arm A with a Lean 4 syntax block, thinking off (Neel's
# decision). prompts/arm_A.txt is edited in place; the first run's version is in git (commit c475f95).
# qwen_a2 is historical: its prompt was arm_A.txt at commit f5faca3 (saved in summary.json "rerun").
RERUN_CONFIGS = {"qwen_a2": ("qwen3-8b", "prompts/arm_A.txt", False),
                 # third: arm A back to its first instruction line, plus the fixed few-shot block
                 "qwen_a3": ("qwen3-8b", "prompts/arm_A.txt", False)}
RERUN_FEWSHOT = {"qwen_a3": "prompts/fewshot.txt"}
RERUN_OUT = {"qwen_a2": PILOT_A2, "qwen_a3": RUN_DIR / "pilot_a3.jsonl.gz"}
ALL_CONFIGS = {**CONFIGS, **RERUN_CONFIGS}
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


def all_rows():
    """Pilot rows from the first run and every rerun that exists."""
    return read_rows(PILOT) + [r for path in RERUN_OUT.values() if path.exists() for r in read_rows(path)]


def config_cfg(cfg, name):
    model_key, _, thinking = ALL_CONFIGS[name]
    c = copy.deepcopy(cfg)
    if thinking is not None:
        c["models"][model_key]["enable_thinking"] = thinking
    return c


def container_start():
    """Start time of the pod's container (PID 1), UTC."""
    out = subprocess.run(["ps", "-o", "lstart=", "-p", "1"], capture_output=True, text=True, check=True).stdout
    return datetime.strptime(" ".join(out.split()), "%a %b %d %H:%M:%S %Y").replace(tzinfo=timezone.utc)


def gpu_balance(cfg, start, until, costs_path=COSTS_PATH, chunk=CHUNK):
    """Append one `gpu` row so this pod session's GPU hours equal its wall clock since `start` (rows
    logged before `start` belong to earlier sessions and are left alone)."""
    rows = read_jsonl(costs_path) if costs_path.exists() else []
    logged = sum(r.get("hours", 0) for r in rows if r["chunk"] == chunk and r["purpose"] == "gpu"
                 and datetime.fromisoformat(r["time"]) >= start)
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


def pod(cfg, summary, argv=()):
    """Record this pod session (container start, setup time) and make it the current one."""
    session = {"container_start": container_start().isoformat(), "gpu_type": cfg["gpu"]["type"],
               "usd_per_hour": cfg["gpu"]["usd_per_hour"], "setup_hours": setup_hours()}
    sessions = summary.setdefault("pod_sessions", [summary["pod"] | {"setup_hours": summary.get("setup_hours")}]
                                  if "pod" in summary else [])
    if not sessions or sessions[-1]["container_start"] != session["container_start"]:
        sessions.append(session)
    summary["pod"] = session
    summary["setup_hours"] = session["setup_hours"]


def run_config(cfg, summary, name, items, checker, timing):
    """Generate (timed once per configuration), then score every output and check memorization."""
    model_key, prompt, _ = ALL_CONFIGS[name]
    workers = cfg["generation"]["workers"]
    c = config_cfg(cfg, name)
    instructions = load_instructions(prompt)
    fewshot = load_fewshot(RERUN_FEWSHOT.get(name))
    genc = formalizer_client(c, model_key, CHUNK, run_id=f"pilot_{name}")
    judge = LLMClient(c, CHUNK, run_id=f"pilot_{name}")
    if name not in timing:
        t0 = time.monotonic()  # generation alone, all items at `workers` concurrency
        with ThreadPoolExecutor(workers) as pool:
            outs = list(pool.map(lambda it: generate(genc, c, model_key, instructions, it, fewshot=fewshot), items))
        seconds = time.monotonic() - t0
        tokens = sum((o.get("usage") or {}).get("completion_tokens") or 0 for o in outs)
        timing[name] = {"items": len(items), "gen_seconds": seconds, "completion_tokens": tokens,
                        "tokens_per_second": tokens / seconds if seconds else None, "workers": workers}
        save_summary(summary)
    with ThreadPoolExecutor(workers) as pool:  # generations now come from the cache
        rs = list(pool.map(lambda it: score_row(c, name, model_key, None, None, "val", instructions, it, 0,
                                                genc, judge, checker, fewshot=fewshot), items))
    statements = [r["normalized"] for r in rs if r["normalized"]]
    matched = memorization.exact_matches(checker, memorization.load_index(),
                                         [it for it, r in zip(items, rs) if r["normalized"]], statements)
    for r, m in zip([r for r in rs if r["normalized"]], matched):
        r["memorized"] = m
    for r in rs:
        r["config"], r["model"] = name, model_key
    print(name, json.dumps(timing[name]))
    return rs


def gen(cfg, summary, argv=()):
    pod(cfg, summary)
    gpu(cfg, summary)
    items = pilot_items(cfg)
    checker = AxleChecker(cfg["axle"])
    # A rerun finds earlier generations in the cache, so a configuration is timed only once: its timing
    # is saved as soon as it is measured, or read back from an earlier run's log (--timing-log).
    timing = summary.setdefault("gen_timing", {})
    if "--timing-log" in argv:
        for line in open(argv[argv.index("--timing-log") + 1]):
            name, _, rest = line.strip().partition(" ")
            if name in CONFIGS and rest.startswith("{"):
                timing[name] = {**json.loads(rest), "source": "earlier run's log"}
    rows = [r for name in CONFIGS for r in run_config(cfg, summary, name, items, checker, timing)]
    write_rows(PILOT, rows)
    summary["gen"] = {"item_ids": [it["id"] for it in items], "timing": timing}
    gpu(cfg, summary)


def rerun(cfg, summary, argv=()):
    """Qwen3-8B, thinking off, with a revised arm A prompt, on the same 30 pilot items.
    --config qwen_a2 (syntax block) or qwen_a3 (few-shot, the default)."""
    name = argv[argv.index("--config") + 1] if "--config" in argv else "qwen_a3"
    pod(cfg, summary)
    gpu(cfg, summary)
    items = pilot_items(cfg)
    assert [it["id"] for it in items] == summary["gen"]["item_ids"], "pilot items changed"
    text = load_instructions(RERUN_CONFIGS[name][1])
    fewshot = load_fewshot(RERUN_FEWSHOT.get(name))
    record = {"config": name, "prompt": text, "prompt_sha256": hashlib.sha256(text.encode()).hexdigest(),
              "fewshot_sha256": hashlib.sha256(fewshot.encode()).hexdigest() if fewshot else None}
    summary["rerun" if name == "qwen_a2" else f"rerun_{name}"] = record
    timing = summary.setdefault("gen_timing", {})
    rows = run_config(cfg, summary, name, items, AxleChecker(cfg["axle"]), timing)
    write_rows(RERUN_OUT[name], rows)
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


# Label mix: half Qwen3-8B (the latest rerun first, topped up from the earlier thinking-off runs),
# the rest ReForm-8B.
LABEL_GROUPS = (("qwen_a3", "qwen_a2", "qwen_nothink"), ("reform",))


def fewshot_pool(checker, items):
    """Train items usable as examples: no helper definitions (an example shows no context), and the
    reference compiles with autoImplicit off (our rule for candidates; excludes pnv_280)."""
    from src.scoring.compile import compile_candidate
    pool = []
    for it in sorted(items, key=lambda it: it["id"]):
        if it["helper"].strip():
            continue
        if compile_candidate(checker, it, normalize_statement(it["formal_stmt"])).passed:
            pool.append(it)
    return pool


def sorry_ending(stmt):
    """The reference text with its proof replaced by exactly `:= by sorry`."""
    import re
    head = re.sub(r":=\s*(by\s+)?sorry\s*$", "", stmt.rstrip())
    assert head != stmt.rstrip(), "reference does not end in sorry"
    return head.rstrip() + " := by sorry"


def fewshot_block(examples):
    """Each example is laid out like a real query (English, then its context block) and then the answer."""
    parts = [f"Example {k}:\n{it['informal_stmt']}\n{context_block(it)}Answer:\n```lean4\n{sorry_ending(it['formal_stmt'])}\n```"
             for k, it in enumerate(examples, 1)]
    return "\n\n".join(parts)


def fewshot(cfg, summary, argv=()):
    f = cfg["fewshot"]
    pool = fewshot_pool(AxleChecker(cfg["axle"]), gepa_items("train"))
    examples = random.Random(f["seed"]).sample(pool, f["n"])
    (ROOT / f["path"]).write_text(fewshot_block(examples) + "\n")
    if f.get("ids") != [it["id"] for it in examples]:
        raise SystemExit(f"config fewshot.ids {f.get('ids')} differs from the seeded draw {[it['id'] for it in examples]}")
    summary["fewshot"] = {"seed": f["seed"], "pool_size": len(pool), "ids": [it["id"] for it in examples],
                          "names": [it["name"] for it in examples], "path": f["path"]}


def preflight_verdict(check):
    """Pass/fail for one live API check: a new paid cost row (so not a cache hit), a normal stop, and
    the check's own content test."""
    reasons = []
    if check.get("error"):
        reasons.append(f"error: {check['error'][:200]}")
    if not check.get("new_cost_rows"):
        reasons.append("no new cost row (cache hit or not called)")
    if check.get("finish_reason") not in (None, "stop") or check.get("finish_reason") == "length":
        reasons.append(f"finish_reason {check.get('finish_reason')}")
    kind = check["kind"]
    if kind == "reflection":
        new = (check.get("new_instruction") or "").strip()
        if not new or new == check["seed"].strip():
            reasons.append("no new instruction")
        if check.get("failures"):
            reasons.append(f"reflection failures: {check['failures'][:1]}")
    elif kind == "arm_f" and check.get("format_failure"):
        reasons.append("no Lean statement extracted")
    elif kind == "judge" and check.get("verdict") not in ("faithful", "unfaithful"):
        reasons.append(f"verdict {check.get('verdict')}")
    return {"pass": not reasons, "reasons": reasons}


PREFLIGHT_CHECKS = ("reflection_minibatch_3", "reflection_long_15", "arm_f_generate",
                    "opt_judge_pnv_258", "ref_judge_pnv_258", "opt_judge_pnv_260", "ref_judge_pnv_260")
# The checks that gate the GEPA pilot (Neel, 2026-10-22): GEPA reflects on minibatches of 3, so a
# 15-record reflection never happens in a run, and GEPA never calls arm F. Both still run and are reported.
GATE_CHECKS = ("reflection_minibatch_3", "opt_judge_pnv_258", "ref_judge_pnv_258", "opt_judge_pnv_260", "ref_judge_pnv_260")


def preflight_gate(report, now, max_age_hours=24):
    """(ok, reasons): every gate check present and passed, the latest run under max_age_hours old."""
    reasons = []
    by_name = {c["name"]: c for c in report.get("checks", [])}
    for name in GATE_CHECKS:
        if name not in by_name:
            reasons.append(f"{name}: missing")
        elif not by_name[name]["pass"]:
            reasons.append(f"{name}: failed {by_name[name]['reasons']}")
    stamp = report.get("time") or (report.get("date", "1970-01-01") + "T00:00:00+00:00")
    age = (now - datetime.fromisoformat(stamp)).total_seconds() / 3600
    if age > max_age_hours:
        reasons.append(f"preflight is {age:.1f} h old (limit {max_age_hours} h)")
    return not reasons, reasons


def preflight_ok(cfg, summary, argv=()):
    """Exit 0 only if the committed preflight passed its gate checks and is recent (the pod's gate before GEPA)."""
    ok, reasons = preflight_gate(json.loads((RUN_DIR / "api_preflight.json").read_text()), datetime.now(timezone.utc))
    print("preflight gate:", "open" if ok else "closed", *reasons, sep="\n  ")
    if not ok:
        raise SystemExit(1)


def fresh_cache_dir(root=ROOT / "cache/preflight"):
    """A cache directory no earlier call has used, so the preflight's calls cannot be cache hits."""
    path = root / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    assert not path.exists()
    return path


def feedback_records(checker, val, rows):
    """GEPA's reflection records (Inputs, Generated Outputs, Feedback) for saved pilot rows on val items."""
    from src.gepa_adapter import feedback_text
    from src.scoring.score import prepare
    out = []
    for r in rows:
        p = prepare(checker, val[r["item_id"]], r["output"])
        trace = {**p, "judge": {"verdict": r["judge_verdict"], "reason": r["judge_reason"]} if r["compiled"] else None,
                 "score": r["judge_score"] or 0}
        out.append({"Inputs": user_message("", val[r["item_id"]]).lstrip("\n"),
                    "Generated Outputs": p["extracted"] or "(no Lean statement found)", "Feedback": feedback_text(trace)})
    return out


def reflection_load(client, model, max_tokens, prompts, seeds, costs_path=COSTS_PATH):
    """All prompts as concurrent reflection calls (chunk 5 runs six GEPA runs at once). Per call: time,
    usage, cost and preflight_verdict; plus wall time and passes. Information only: it gates nothing."""
    from gepa.strategies.instruction_proposal import InstructionProposalSignature
    count = lambda: sum(1 for _ in open(costs_path)) if costs_path.exists() else 0
    before, t0 = count(), time.monotonic()

    def one(i):
        start = time.monotonic()
        try:
            out, error = client.chat_full(model, [{"role": "user", "content": prompts[i]}], purpose="reflection",
                                          max_tokens=max_tokens), None
        except Exception as e:
            out, error = {}, f"{type(e).__name__}: {e}"[:300]
        text = out.get("text") or ""
        c = {"name": f"reflection_load_{i}", "kind": "reflection", "model": model, "records": 3,
             "seconds": time.monotonic() - start, "new_cost_rows": 1 if out else 0, "error": error,
             "finish_reason": out.get("finish_reason"), "usage": out.get("usage"),
             "usd": client.cost(model, out["usage"]) if out else 0, "seed": seeds[i],
             "new_instruction": InstructionProposalSignature.output_extractor(text)["new_instruction"] if text else ""}
        return {**c, **preflight_verdict(c)}

    with ThreadPoolExecutor(len(prompts)) as pool:
        calls = list(pool.map(one, range(len(prompts))))
    return {"calls": calls, "concurrent": len(prompts), "wall_seconds": time.monotonic() - t0,
            "passed": sum(c["pass"] for c in calls), "new_cost_rows": count() - before,
            "usd": sum(c["usd"] for c in calls)}


def reflect_load(cfg, summary, argv=()):
    """Six concurrent live 3-record reflections on different pilot minibatches (Neel, 2026-10-22).
    Writes runs/chunk4/reflection_load.json; never touches api_preflight.json, so the gate can't change."""
    from gepa.strategies.instruction_proposal import InstructionProposalSignature
    n = int(argv[argv.index("--n") + 1]) if "--n" in argv else 6
    checker = AxleChecker(cfg["axle"])
    val = {it["id"]: it for it in gepa_items("val")}
    rows = read_rows(RERUN_OUT["qwen_a3"])
    seed = load_instructions("prompts/arm_A.txt")
    prompts = [InstructionProposalSignature.prompt_renderer(
        {"current_instruction_doc": seed, "dataset_with_feedback": feedback_records(checker, val, rows[3 * i:3 * i + 3])})
        for i in range(n)]
    client = LLMClient(cfg, CHUNK, run_id="preflight_load", cache_dir=fresh_cache_dir())
    t = datetime.now(timezone.utc).isoformat(timespec="seconds")
    out = reflection_load(client, cfg["gepa"]["reflection_model"], cfg["gepa"]["reflection_max_tokens"], prompts, [seed] * n)
    out = {"time": t, "limits": dict(zip(("timeout_seconds", "retries"), client.limits("reflection"))), **out}
    (RUN_DIR / "reflection_load.json").write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
    summary["reflection_load"] = {k: out[k] for k in ("time", "concurrent", "wall_seconds", "passed", "usd", "limits")}
    summary["reflection_load"]["call_seconds"] = [round(c["seconds"], 1) for c in out["calls"]]
    print(json.dumps(summary["reflection_load"]))


def preflight_limits(cfg, argv):
    """Preflight-only call limits, on the in-memory cfg: --once means one attempt per call, no retries
    (a rerun Neel asked to make exactly once); --cap S lowers every per-attempt timeout to at most S seconds."""
    llm = cfg["llm"]
    if "--once" in argv:
        llm["retries"] = llm["long_retries"] = 0
        for lim in llm.get("purpose_limits", {}).values():
            lim["retries"] = 0
    if "--cap" in argv:
        cap = float(argv[argv.index("--cap") + 1])
        llm["timeout_seconds"] = min(llm["timeout_seconds"], cap)
        llm["long_timeout_seconds"] = min(llm.get("long_timeout_seconds", cap), cap)
        for lim in llm.get("purpose_limits", {}).values():
            lim["timeout_seconds"] = min(lim["timeout_seconds"], cap)


def preflight(cfg, summary, argv=()):
    """Live tests of every API model GEPA and the final eval need, before paying for a pod."""
    from gepa.strategies.instruction_proposal import InstructionProposalSignature
    from src.runner import ReflectionLM
    from src.scoring import judge as judges
    from src.scoring.score import prepare

    def snap():
        rows = read_jsonl(COSTS_PATH) if COSTS_PATH.exists() else []
        return len(rows), sum(r["usd"] for r in rows)

    def delta(before):
        n, usd = snap()
        return {"new_cost_rows": n - before[0], "usd": usd - before[1]}

    only = set(argv[argv.index("--only") + 1].split(",")) if "--only" in argv else None
    preflight_limits(cfg, argv)
    want = lambda name: only is None or name in only
    checker = AxleChecker(cfg["axle"])
    cache = fresh_cache_dir() if "--fresh" in argv else None  # a new cache dir: every call is live
    client = LLMClient(cfg, CHUNK, run_id="preflight", cache_dir=cache)
    val = {it["id"]: it for it in gepa_items("val")}
    rows = read_rows(RERUN_OUT["qwen_a3"])
    seed = load_instructions("prompts/arm_A.txt")
    checks = []

    records = lambda rs: feedback_records(checker, val, rs)

    for label, rs in (("reflection_minibatch_3", rows[:3]), ("reflection_long_15", rows[3:18])):
        if not want(label):
            continue
        prompt = InstructionProposalSignature.prompt_renderer({"current_instruction_doc": seed, "dataset_with_feedback": records(rs)})
        lm = ReflectionLM(client, cfg["gepa"]["reflection_model"], cfg["gepa"]["reflection_max_tokens"])
        before, t0 = snap(), time.monotonic()
        try:
            text = lm(prompt)
        except Exception:
            text = ""
        reply = client.chat_full(cfg["gepa"]["reflection_model"], [{"role": "user", "content": prompt}], purpose="reflection",
                                 max_tokens=cfg["gepa"]["reflection_max_tokens"]) if lm.calls and not any(
            "HTTP" in f or "Error" in f for f in lm.failures) else {}
        seconds = time.monotonic() - t0
        full = reply  # the same call again is a cache hit: it returns finish_reason and usage
        new = InstructionProposalSignature.output_extractor(text)["new_instruction"] if text else ""
        error = lm.failures[0] if lm.failures else None
        checks.append({"name": label, "kind": "reflection", "model": cfg["gepa"]["reflection_model"], "records": len(rs),
                       "prompt_chars": len(prompt), "seconds": seconds, **delta(before),
                       "finish_reason": full.get("finish_reason"), "usage": full.get("usage"), "failures": lm.failures,
                       "seed": seed, "new_instruction": new, "error": error})

    train = sorted(gepa_items("train"), key=lambda it: it["id"])
    item = next(it for it in train if it["id"] not in cfg["fewshot"]["ids"])
    genc = formalizer_client(cfg, "arm_f", CHUNK, run_id="preflight", cache_dir=cache)
    before, t0 = snap(), time.monotonic()
    out, error = None, None
    if want("arm_f_generate"):
        try:  # an API failure is a failed check, recorded like any other, never a crash
            out = generate(genc, cfg, "arm_f", load_instructions(cfg["arms"]["F"]["prompt"]), item,
                           fewshot=load_fewshot(cfg["arms"]["F"].get("fewshot")))
        except Exception as e:
            error = f"{type(e).__name__}: {e}"[:300]
            checks.append({"name": "arm_f_generate", "kind": "arm_f", "model": cfg["models"]["arm_f"]["served_name"],
                           "item_id": item["id"], "seconds": time.monotonic() - t0, **delta(before), "error": error})
    p = prepare(checker, item, out["text"]) if out else None
    if out: checks.append({"name": "arm_f_generate", "kind": "arm_f", "model": cfg["models"]["arm_f"]["served_name"], "item_id": item["id"],
                   "seconds": time.monotonic() - t0, **delta(before), "finish_reason": out["finish_reason"],
                   "usage": out.get("usage"), "format_failure": p["format_failure"], "compiled": p["compiled"],
                   "extracted": p["extracted"]})

    for r in [r for r in rows if r["compiled"]][:2]:
        if not want(f"opt_judge_{r['item_id']}"):
            continue
        it = val[r["item_id"]]
        for name, call, model in (("opt_judge", lambda: judges.optimization_judge(client, cfg, it["informal_stmt"], r["normalized"]),
                                   cfg["judges"]["optimization"]),
                                  ("ref_judge", lambda: judges.reference_judge(client, cfg, it["informal_stmt"],
                                                                               normalize_statement(it["formal_stmt"]), r["normalized"]),
                                   cfg["judges"]["reference"])):
            before, t0 = snap(), time.monotonic()
            try:
                v = call()
            except Exception as e:  # recorded as a failed check
                v = {"verdict": "error", "reason": f"{type(e).__name__}: {e}"}
            checks.append({"name": f"{name}_{r['item_id']}", "kind": "judge", "model": model, "seconds": time.monotonic() - t0,
                           **delta(before), "verdict": v["verdict"], "reason": v["reason"][:300]})

    for c in checks:
        c.update(preflight_verdict(c), max_tokens=cfg["gepa"]["reflection_max_tokens"] if c["kind"] == "reflection" else None)
    path = RUN_DIR / "api_preflight.json"
    if only is None and path.exists():  # a full rerun: keep the earlier results under their date
        earlier = json.loads(path.read_text())
        dated = RUN_DIR / f"api_preflight_{earlier.get('date', '2026-10-18')}.json"
        if not dated.exists():
            dated.write_text(path.read_text())
    checks_date = datetime.now(timezone.utc).date().isoformat()
    checks_time = datetime.now(timezone.utc).isoformat(timespec="seconds")
    if only is not None and path.exists() and json.loads(path.read_text()).get("date") != checks_date:
        old = json.loads(path.read_text())  # an older day's file: archive it, never merge across days
        dated = RUN_DIR / f"api_preflight_{old.get('date', '2026-10-18')}.json"
        if not dated.exists():
            dated.write_text(path.read_text())
        path.unlink()
    if only is not None and path.exists():  # rerun of some checks: keep the others, record the earlier attempt
        old = json.loads(path.read_text())
        rerun = {c["name"] for c in checks}
        earlier = old.get("earlier_attempts", []) + [c for c in old["checks"] if c["name"] in rerun]
        checks = [c for c in old["checks"] if c["name"] not in rerun] + checks
        path.write_text(json.dumps({"date": checks_date, "time": checks_time, "cache_dir": str(cache) if cache else None,
                                    "checks": checks, "earlier_attempts": earlier}, indent=1, ensure_ascii=False) + "\n")
    else:
        path.write_text(json.dumps({"date": checks_date, "time": checks_time, "cache_dir": str(cache) if cache else None,
                                    "checks": checks}, indent=1, ensure_ascii=False) + "\n")
    summary["preflight"] = {"all_pass": all(c["pass"] for c in checks),
                            "checks": {c["name"]: {"pass": c["pass"], "reasons": c["reasons"], "model": c["model"],
                                                   "seconds": round(c["seconds"], 1), "usd": c["usd"], "usage": c.get("usage")}
                                       for c in checks}}


def pick_label_rows(rows, cfg, groups=LABEL_GROUPS):
    """20 compiled outputs on distinct items: half from the first group, the rest from the second,
    each filled from its configurations in order; then shuffled."""
    rng = random.Random(cfg["pilot"]["seed"])
    n = cfg["pilot"]["label_items"]
    used, picked = set(), []
    for g, names in enumerate(groups):
        quota = n // 2 if g == 0 else n - len(picked)
        taken = 0
        for name in names:
            pool = [r for r in rows if r["config"] == name and r["compiled"] and r["ref_verdict"] and r["item_id"] not in used]
            rng.shuffle(pool)
            for r in pool[: quota - taken]:
                picked.append(r)
                used.add(r["item_id"])
                taken += 1
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
    mapping, records = label_records(pick_label_rows(all_rows(), cfg), items)
    write_jsonl(RUN_DIR / "label_sample.jsonl", mapping)
    client = LLMClient(cfg, CHUNK, run_id="pilot_label")
    build_page(client, cfg, records, RUN_DIR / "labeling.html", page_key="chunk4-pilot")
    summary["label"] = {"n": len(mapping), "by_config": {c: sum(m["config"] == c for m in mapping) for c in ALL_CONFIGS}}


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
    out, per = agreement(all_rows(), read_jsonl(RUN_DIR / "label_sample.jsonl"), labels)
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


def reliability(cost_rows, failure_rows, run_id):
    """Reflection latency and hung or failed API attempts for one GEPA run, from the raw logs."""
    secs = sorted(c["seconds"] for c in cost_rows if c.get("run_id") == run_id and c["purpose"] == "reflection" and "seconds" in c)
    fails = [f for f in failure_rows if f.get("run_id") == run_id]
    timeouts = [f for f in fails if f["kind"] == "timeout"]
    refl_fails = [f for f in fails if f["purpose"] == "reflection"]
    attempts = len(secs) + len(refl_fails)
    return {"reflection_calls": len(secs), "reflection_median_s": secs[len(secs) // 2] if secs else None,
            "reflection_slowest_s": secs[-1] if secs else None, "failed_attempts": len(fails), "timed_out": len(timeouts),
            "reflection_hang_rate": len(refl_fails) / attempts if attempts else 0.0}


def overnight_hours(m, rel, cfg):
    """Projected chunk 5 wall clock (hours): the six GEPA runs in parallel (the slowest, ReForm-8B, sets the
    pace, scaled from the pilot's wall time per metric call), expected stall from hung reflection calls
    (hang rate x projected reflection calls per run x the reflection cap), the final eval, and setup."""
    budget = cfg["gepa"]["max_metric_calls"]
    reform_ratio = m["gen_s_per_item"]["reform"] / m["gen_s_per_item"]["qwen"]
    gepa = budget * m["gepa_wall_s_per_call"] * max(1.0, reform_ratio) / 3600
    calls_per_run = rel["reflection_calls"] / m["pilot_metric_calls"] * budget if m["pilot_metric_calls"] else 0.0
    cap = cfg["llm"].get("purpose_limits", {}).get("reflection", {}).get("timeout_seconds", cfg["llm"]["long_timeout_seconds"])
    stall = rel["reflection_hang_rate"] * calls_per_run * cap / 3600
    final = m["final_eval_hours"]
    return {"gepa_parallel_h": gepa, "expected_hang_stall_h": stall, "final_eval_h": final, "setup_h": m["setup_hours"],
            "total_h": gepa + stall + final + m["setup_hours"], "reflection_calls_per_run": calls_per_run}


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


def refuse_finished_run(out_dir):
    """GEPA resumes from runs/<run_id>/gepa; a finished or stopped run there must be moved aside first,
    or a relaunch would end at once with the old state (chunk 4: the failed Kimi-K2.6 run)."""
    for marker in ("DONE", "STOPPED"):
        if (out_dir / marker).exists():
            raise SystemExit(f"{out_dir} already has {marker}; move it aside before relaunching")


def gepa(cfg, summary, argv=()):
    from scripts import gepa_run
    p = cfg["pilot"]
    spec = dict(p["gepa_run"])
    if "--thinking" in argv:
        spec["enable_thinking"] = argv[argv.index("--thinking") + 1] == "on"
    cfg["gepa"]["runs"] = {p["gepa_run_id"]: spec}
    refuse_finished_run(ROOT / "runs" / p["gepa_run_id"])
    summary["gepa_launch"] = {"run_id": p["gepa_run_id"], **spec,
                              "started": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    save_summary(summary)
    gepa_run.run(cfg, p["gepa_run_id"], CHUNK)


def costs(cfg, summary, argv=()):
    summary["costs"] = summarize([r for r in read_jsonl(COSTS_PATH) if r["chunk"] == CHUNK])
    summary["costs_all_chunks_usd"] = sum(r["usd"] for r in read_jsonl(COSTS_PATH))


def project(cfg, summary, argv=()):
    rows = all_rows()
    crow = read_jsonl(COSTS_PATH)
    stats = {name: config_stats(rows, crow, name) for name in ALL_CONFIGS if any(r["config"] == name for r in rows)}
    t = summary["gen_timing"]
    run_id = summary["gepa_launch"]["run_id"]
    qcfg = next(k for k in ("qwen_a3", "qwen_a2", "qwen_nothink") if k in stats)
    cand = json.loads((ROOT / "runs" / run_id / "candidates.json").read_text())
    calls = cand["total_metric_calls"]
    gepa_rows = [c for c in crow if c.get("run_id") == run_id]
    gepa_hours = sum(c.get("hours", 0) for c in gepa_rows if c["purpose"] == "gpu")
    failures_path = COSTS_PATH.parent / "api_failures.jsonl"
    rel = reliability(crow, read_jsonl(failures_path) if failures_path.exists() else [], run_id)
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
    m2 = {**m, "gepa_wall_s_per_call": gepa_hours * 3600 / calls, "pilot_metric_calls": calls,
          "final_eval_hours": proj["final_eval_gpu_hours"]}
    summary["go_info"] = {"reliability": rel, "overnight_hours": overnight_hours(m2, rel, cfg)}


# Patterns behind compile failures, counted on the raw output's extracted statement.
PATTERNS = {
    "old big-operator binder (∑/∏ x in s)": r"[∑∏]\s*\S+\s+in\s",
    "Lean 3 lambda (λ x, or fun x,)": r"(λ|fun)\s[^=↦]*?,",
    "Lean 3 snake_case Mathlib names (at_top, is_..., ...)": r"\b(at_top|at_bot|is_[a-z_]+|nat\.|int\.|real\.)",
    "Lean 3 norm bars (∥x∥)": r"∥",
    "`variable` lines in the answer block (dropped: one theorem per answer)": r"^\s*variables?\s",
}


def diagnose_rows(rows):
    """Per configuration: compile statuses, pattern counts among compile failures, and the first line
    of each Lean error grouped by kind."""
    import re
    from collections import Counter
    out = {}
    for name in [n for n in ALL_CONFIGS if any(r["config"] == n for r in rows)]:
        rs = [r for r in rows if r["config"] == name]
        failed = [r for r in rs if not r["compiled"]]
        answer = lambda r: r["output"].rsplit("</think>", 1)[-1]
        out[name] = {
            "outputs": len(rs), "compile_failures": len(failed),
            "patterns_in_failures": {k: sum(bool(re.search(p, answer(r), re.M)) for r in failed) for k, p in PATTERNS.items()},
            "failures_with_any_pattern": sum(any(re.search(p, answer(r), re.M) for p in PATTERNS.values()) for r in failed),
            "compile_status": dict(Counter(r["compile_status"] for r in rs)),
        }
    return out


def diagnose(cfg, summary, argv=()):
    rows = all_rows()
    d = diagnose_rows(rows)
    # Lean's own error kinds, recompiled through AXLE (free and cached).
    from collections import Counter
    import re
    checker = AxleChecker(cfg["axle"])
    items = {it["id"]: it for it in gepa_items("val")}
    from src.scoring.score import prepare
    for name in d:
        kinds = Counter()
        for r in rows:
            if r["config"] == name and not r["compiled"] and r["normalized"]:
                errs = prepare(checker, items[r["item_id"]], r["output"])["lean_errors"]
                first = str(errs[0]) if errs else "(no error text)"
                m = re.search(r"error(\([^)]*\))?:\s*([^\n`']{0,60})", first)
                kinds[(m.group(1) or "") + " " + m.group(2).strip() if m else first[:60]] += 1
        d[name]["first_error_kinds"] = dict(kinds.most_common(8))
    summary["diagnose"] = d


def stats(cfg, summary, argv=()):
    """Per-configuration pilot numbers and the go checks that need no labels or GEPA run."""
    rows, crow = all_rows(), read_jsonl(COSTS_PATH)
    summary["stats"] = st = {name: config_stats(rows, crow, name) for name in ALL_CONFIGS if any(r["config"] == name for r in rows)}
    qwen = [k for k in ("qwen_nothink", "qwen_think", "qwen_a2", "qwen_a3") if k in st]
    summary["go_partial"] = {
        "qwen_truth_faithful_rate": {k: st[k]["truth_faithful_rate"] for k in qwen},
        "qwen_go_10_to_70": {k: 10 <= st[k]["truth_faithful_rate"] <= 70 for k in qwen},
        "exact_match_rate_max": max(v["exact_match_rate"] for v in st.values()),
        "not_measured": ["reference judge agreement (labels)", "projected total (GEPA pilot run)"],
    }


def records_from_old_page(text):
    """The 20 records and their glosses from the first labeling page's HTML (the glosses were made on a
    pod whose cache is gone; reusing them keeps the page's text unchanged)."""
    import html as h
    import re
    cards = re.findall(r'<section class="card" data-id="([^"]+)">.*?<p class="english">(.*?)</p>.*?'
                       r'<h3>Reference</h3><pre>(.*?)</pre><p class="gloss">(.*?)</p>.*?'
                       r'<h3>Candidate</h3><pre>(.*?)</pre><p class="gloss">(.*?)</p>', text, re.S)
    return [dict(zip(("label_id", "english", "reference", "reference_gloss", "candidate", "candidate_gloss"),
                     map(h.unescape, c))) for c in cards]


def relabel(cfg, summary, argv=()):
    """Rebuild the labeling page (new layout) from the first page's records; same items, glosses and key."""
    from pathlib import Path
    from src.scoring.labeling import render_page
    old = Path(argv[argv.index("--old") + 1]).expanduser()
    out = Path(argv[argv.index("--out") + 1]).expanduser()
    records = records_from_old_page(old.read_text())
    mapping = read_jsonl(RUN_DIR / "label_sample.jsonl")
    assert [r["label_id"] for r in records] == [m["label_id"] for m in mapping], "records differ from label_sample.jsonl"
    (RUN_DIR / "label_records.json").write_text(json.dumps(records, indent=1, ensure_ascii=False) + "\n")
    out.write_text(render_page(records, "chunk4-pilot"))
    summary["relabel"] = {"records": len(records), "page_key": "chunk4-pilot", "out": str(out)}


STEPS = {"preflight_ok": preflight_ok, "reflect_load": reflect_load, "relabel": relabel, "preflight": preflight, "fewshot": fewshot, "pod": pod, "rerun": rerun, "stats": stats, "diagnose": diagnose, "gen": gen, "armf": armf, "label": label, "gepa": gepa, "gpu": gpu, "agree": agree,
         "costs": costs, "project": project}


def report():
    s = load_summary()
    print(f"- Pod: {s['pod']['gpu_type']} at ${s['pod']['usd_per_hour']}/hr; container start {s['pod']['container_start']}")
    for name, st in s["stats"].items():
        t = s["gen_timing"][name]
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
    if "go_info" in s:
        r, o = s["go_info"]["reliability"], s["go_info"]["overnight_hours"]
        print(f"| Reflection latency (median / slowest) | {r['reflection_median_s']} s / {r['reflection_slowest_s']} s | info |")
        print(f"| Hung or timed-out calls | {r['timed_out']} timed out, {r['failed_attempts']} failed attempts; reflection hang rate {100 * r['reflection_hang_rate']:.1f}% | info |")
        print(f"| Projected overnight run | {o['total_h']:.1f} h (GEPA {o['gepa_parallel_h']:.1f} + hang stall {o['expected_hang_stall_h']:.1f} + final eval {o['final_eval_h']:.1f} + setup {o['setup_h']:.1f}) | info |")
    c = s["costs"]
    print(f"\n- Chunk 4 cost: ${c['usd_total']:.2f}; by purpose: "
          + ", ".join(f"{k} {v['calls']} rows ${v['usd']:.3f}" for k, v in c["by_purpose"].items()))
    print("\n5 random pilot rows (seed 0):")
    for r in random.Random(0).sample(all_rows(), 5):
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
