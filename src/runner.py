"""One GEPA run: gepa.optimize with library defaults, our adapter, our reflection client.

Writes runs/<run_id>/: gepa/ (GEPA's own state; it resumes from here after a crash),
best_prompt.txt, candidates.json and DONE. A budget stop, an AXLE outage or a failed reflection call
leaves no DONE marker. GEPA itself catches reflection errors and carries on with the same candidate, so
without the check below a run whose reflection model is down would end "done" with only the seed.
"""
import copy
import json

import gepa

from src.config import ROOT
from src.data.firewall import gepa_items
from src.gepa_adapter import COMPONENT, AxleOutage, FormalizerAdapter
from src.llm import BudgetExceeded
from src.prompting import load_fewshot, load_instructions


class ReflectionFailed(RuntimeError):
    """A reflection call failed after the client's retries; the run stops (and resumes later)."""


class ReflectionLM:
    """GEPA's LanguageModel protocol, `(str | list[dict]) -> str`, through our cached, cost-logged client.
    Failures are recorded, because GEPA swallows the exception."""

    def __init__(self, client, model, max_tokens):
        self.client, self.model, self.max_tokens = client, model, max_tokens
        self.calls = 0
        self.failures = []

    def __call__(self, prompt):
        messages = [{"role": "user", "content": prompt}] if isinstance(prompt, str) else prompt
        self.calls += 1
        try:
            out = self.client.chat_full(self.model, messages, purpose="reflection", max_tokens=self.max_tokens)
        except Exception as e:
            self.failures.append(f"{type(e).__name__}: {e}"[:500])
            raise
        if out["finish_reason"] == "length":  # a cut-off reply would become a broken candidate prompt
            self.failures.append(f"reply cut off at max_tokens={self.max_tokens}")
            raise ReflectionFailed(self.failures[-1])
        return out["text"]


def gepa_trainset(cfg):
    """The train split minus the few-shot example items (their answers are in the prompt). Used by
    every GEPA run, B and D alike; splits.json is unchanged."""
    examples = set(cfg.get("fewshot", {}).get("ids", []))
    return [it for it in gepa_items("train") if it["id"] not in examples]


def run_gepa(cfg, run_id, gen_client, judge_client, reflection_client, checker, runs_dir=ROOT / "runs", on_batch=None):
    spec = cfg["gepa"]["runs"][run_id]
    if "enable_thinking" in spec:  # the chunk 4 pilot run fixes its own thinking mode
        cfg = copy.deepcopy(cfg)
        cfg["models"][spec["model"]]["enable_thinking"] = spec["enable_thinking"]
    out_dir = runs_dir / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    reflection = ReflectionLM(reflection_client, cfg["gepa"]["reflection_model"], cfg["gepa"]["reflection_max_tokens"])

    def batch_done():  # runs after every evaluation, where an exception does reach us
        if reflection.failures:
            raise ReflectionFailed(f"{len(reflection.failures)} reflection call(s) failed; first: {reflection.failures[0]}")
        if on_batch:
            on_batch()

    adapter = FormalizerAdapter(cfg, spec["model"], gen_client, judge_client, checker, on_batch=batch_done,
                                fewshot=load_fewshot(spec.get("fewshot")))
    try:
        result = gepa.optimize(
            seed_candidate={COMPONENT: load_instructions(spec["seed_prompt"])},
            trainset=gepa_trainset(cfg),
            valset=gepa_items("val"),
            adapter=adapter,
            reflection_lm=reflection,
            max_metric_calls=spec.get("max_metric_calls", cfg["gepa"]["max_metric_calls"]),
            seed=spec["seed"],
            run_dir=str(out_dir / "gepa"),
        )
    except (BudgetExceeded, AxleOutage, ReflectionFailed) as e:
        (out_dir / "STOPPED").write_text(f"{type(e).__name__}: {e}\n")
        return {"run_id": run_id, "status": "stopped", "reason": str(e), "metric_calls": adapter.metric_calls}

    if reflection.failures:  # a failure in the last iteration, after the last evaluation
        e = ReflectionFailed(f"{len(reflection.failures)} reflection call(s) failed; first: {reflection.failures[0]}")
        (out_dir / "STOPPED").write_text(f"ReflectionFailed: {e}\n")
        return {"run_id": run_id, "status": "stopped", "reason": str(e), "metric_calls": adapter.metric_calls}
    best = result.best_candidate[COMPONENT]
    (out_dir / "best_prompt.txt").write_text(best + "\n")
    (out_dir / "candidates.json").write_text(json.dumps({
        "run_id": run_id, "best_idx": result.best_idx, "candidates": result.candidates, "parents": result.parents,
        "val_aggregate_scores": result.val_aggregate_scores, "total_metric_calls": result.total_metric_calls,
        "adapter_metric_calls": adapter.metric_calls, "reflection_calls": reflection.calls,
    }, indent=1, ensure_ascii=False) + "\n")
    (out_dir / "DONE").write_text("ok\n")
    return {"run_id": run_id, "status": "done", "best_val": result.val_aggregate_scores[result.best_idx],
            "total_metric_calls": result.total_metric_calls, "metric_calls": adapter.metric_calls}
