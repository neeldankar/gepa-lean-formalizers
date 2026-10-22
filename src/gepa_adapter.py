"""GEPA adapter: one text component, `instructions` (prereg Setup, GEPA). The few-shot block, if
the run has one, is a fixed suffix sent after the instructions on every call; GEPA never sees or
edits it, so every candidate (and best_prompt.txt) is instruction text only.

Every evaluation on the full valset is saved to <candidates_dir>/<sha256(instructions)[:12]>.jsonl (first
line: the instructions; then one row per item and sample with the raw output, extracted Lean, compile
result and judge verdict). Nothing here computes or reads a truth score.

evaluate: formalizer -> judge score (compiled and the optimization judge says faithful), the mean
over samples per item. Traces keep the English, the extracted Lean, Lean's errors and the judge's
verdict and reason. Feedback for the reflection model is Lean's errors plus the judge's verdict
and reason. Only train and validation items ever pass through here (firewall check per batch).
"""
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor

from gepa.core.adapter import EvaluationBatch

from src.axle_check import OUTAGE
from src.data.firewall import check_gepa_batch
from src.generate import generate
from src.prompting import user_message
from src.scoring.score import judge_score

COMPONENT = "instructions"


class AxleOutage(RuntimeError):
    """Raised so the run stops (and resumes later) instead of scoring an outage as a failure."""


def feedback_text(trace):
    if trace["format_failure"]:
        lean = f"Format failure: no Lean 4 theorem statement could be extracted ({trace['format_reason']})."
    elif trace["compiled"]:
        lean = "Lean: the statement compiles."
    else:
        errors = "\n".join(trace["lean_errors"][:5]) or "(no error text)"
        lean = f"Lean: the statement does not compile ({trace['compile_status']}). Errors:\n{errors}"
    if trace["judge"] is None:
        judge = "Judge: not run (the statement must compile first)."
    elif trace.get("judge_missing"):
        judge = "Judge: its reply could not be read twice, so there is no verdict (scored 0 here)."
    else:
        judge = f"Judge verdict: {trace['judge']['verdict']}. Judge reason: {trace['judge']['reason']}"
    return f"Score: {trace['score']}\n{lean}\n{judge}"


class FormalizerAdapter:
    propose_new_texts = None  # use GEPA's default reflective proposer

    def __init__(self, cfg, model_key, gen_client, judge_client, checker, on_batch=None, fewshot="",
                 candidates_dir=None, val_ids=()):
        self.cfg, self.model_key, self.fewshot = cfg, model_key, fewshot
        self.candidates_dir, self.val_ids = candidates_dir, frozenset(val_ids)
        self.gen_client, self.judge_client, self.checker = gen_client, judge_client, checker
        self.samples = cfg["generation"]["samples"]
        self.workers = cfg["generation"]["workers"]
        self.on_batch = on_batch  # e.g. GpuMeter.tick
        self.metric_calls = 0

    def score_one(self, instructions, item, sample):
        out = generate(self.gen_client, self.cfg, self.model_key, instructions, item, sample, fewshot=self.fewshot)
        js = judge_score(self.checker, self.judge_client, self.cfg, item, out["text"])
        if js["judge_score"] is None and not js["judge_missing"]:
            raise AxleOutage(f"AXLE outage on {item['id']}: {js['lean_errors'][:1]}")
        # GEPA needs a number: a missing judge verdict scores 0 here and is saved as "missing"
        return {"judge_missing": js["judge_missing"],"item_id": item["id"], "sample": sample, "output": out["text"], "finish_reason": out["finish_reason"],
                "extracted": js["extracted"], "format_failure": js["format_failure"],
                "format_reason": js["format_reason"], "compiled": js["compiled"],
                "compile_status": js["compile_status"], "lean_errors": js["lean_errors"],
                "judge": js["judge"], "score": js["judge_score"] or 0}

    def save_candidate(self, instructions, results):
        self.candidates_dir.mkdir(parents=True, exist_ok=True)
        path = self.candidates_dir / f"{hashlib.sha256(instructions.encode()).hexdigest()[:12]}.jsonl"
        lines = [json.dumps({"instructions": instructions}, ensure_ascii=False)]
        for r in results:
            j = r["judge"] or {}
            lines.append(json.dumps({
                "item_id": r["item_id"], "sample": r["sample"], "output": r["output"], "extracted": r["extracted"],
                "compile_status": r["compile_status"], "compiled": r["compiled"], "lean_errors": r["lean_errors"],
                "judge_verdict": j.get("verdict"), "judge_reason": j.get("reason"), "score": r["score"],
            }, ensure_ascii=False))
        path.write_text("\n".join(lines) + "\n")

    def evaluate(self, batch, candidate, capture_traces=False):
        check_gepa_batch(batch)
        instructions = candidate[COMPONENT]
        jobs = [(item, s) for item in batch for s in range(self.samples)]
        with ThreadPoolExecutor(self.workers) as pool:
            results = list(pool.map(lambda job: self.score_one(instructions, *job), jobs))
        if self.candidates_dir and self.val_ids and {it["id"] for it in batch} == self.val_ids:
            self.save_candidate(instructions, results)
        outputs, scores, traces = [], [], []
        for i, item in enumerate(batch):
            per_item = results[i * self.samples:(i + 1) * self.samples]
            score = sum(r["score"] for r in per_item) / self.samples
            outputs.append(per_item)
            scores.append(score)
            traces.append({"item": item, "samples": per_item, "score": score})
        self.metric_calls += len(batch)
        if self.on_batch:
            self.on_batch()
        return EvaluationBatch(outputs=outputs, scores=scores, trajectories=traces if capture_traces else None)

    def make_reflective_dataset(self, candidate, eval_batch, components_to_update):
        records = []
        for trace in eval_batch.trajectories:
            for s in trace["samples"]:
                records.append({
                    "Inputs": user_message("", trace["item"]).lstrip("\n"),
                    "Generated Outputs": s["extracted"] or "(no Lean statement found)",
                    "Feedback": feedback_text(s),
                })
        return {c: records for c in components_to_update}
