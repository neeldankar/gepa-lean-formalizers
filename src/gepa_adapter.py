"""GEPA adapter: one text component, `instructions` (prereg Setup, GEPA).

evaluate: formalizer -> judge score (compiled and the optimization judge says faithful), the mean
over samples per item. Traces keep the English, the extracted Lean, Lean's errors and the judge's
verdict and reason. Feedback for the reflection model is Lean's errors plus the judge's verdict
and reason. Only train and validation items ever pass through here (firewall check per batch).
"""
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
    else:
        judge = f"Judge verdict: {trace['judge']['verdict']}. Judge reason: {trace['judge']['reason']}"
    return f"Score: {trace['score']}\n{lean}\n{judge}"


class FormalizerAdapter:
    propose_new_texts = None  # use GEPA's default reflective proposer

    def __init__(self, cfg, model_key, gen_client, judge_client, checker, on_batch=None):
        self.cfg, self.model_key = cfg, model_key
        self.gen_client, self.judge_client, self.checker = gen_client, judge_client, checker
        self.samples = cfg["generation"]["samples"]
        self.workers = cfg["generation"]["workers"]
        self.on_batch = on_batch  # e.g. GpuMeter.tick
        self.metric_calls = 0

    def score_one(self, instructions, item, sample):
        out = generate(self.gen_client, self.cfg, self.model_key, instructions, item, sample)
        js = judge_score(self.checker, self.judge_client, self.cfg, item, out["text"])
        if js["judge_score"] is None:
            raise AxleOutage(f"AXLE outage on {item['id']}: {js['lean_errors'][:1]}")
        return {"item_id": item["id"], "sample": sample, "output": out["text"], "finish_reason": out["finish_reason"],
                "extracted": js["extracted"], "format_failure": js["format_failure"],
                "format_reason": js["format_reason"], "compiled": js["compiled"],
                "compile_status": js["compile_status"], "lean_errors": js["lean_errors"],
                "judge": js["judge"], "score": js["judge_score"]}

    def evaluate(self, batch, candidate, capture_traces=False):
        check_gepa_batch(batch)
        instructions = candidate[COMPONENT]
        jobs = [(item, s) for item in batch for s in range(self.samples)]
        with ThreadPoolExecutor(self.workers) as pool:
            results = list(pool.map(lambda job: self.score_one(instructions, *job), jobs))
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
