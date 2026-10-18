"""One GEPA run: gepa.optimize with library defaults, our adapter, our reflection client.

Writes runs/<run_id>/: gepa/ (GEPA's own state; it resumes from here after a crash),
best_prompt.txt, candidates.json and DONE. A budget stop or AXLE outage leaves no DONE marker.
"""
import json

import gepa

from src.config import ROOT
from src.data.firewall import gepa_items
from src.gepa_adapter import COMPONENT, AxleOutage, FormalizerAdapter
from src.llm import BudgetExceeded
from src.prompting import load_instructions


class ReflectionLM:
    """GEPA's LanguageModel protocol, `(str | list[dict]) -> str`, through our cached, cost-logged client."""

    def __init__(self, client, model, max_tokens):
        self.client, self.model, self.max_tokens = client, model, max_tokens
        self.calls = 0

    def __call__(self, prompt):
        messages = [{"role": "user", "content": prompt}] if isinstance(prompt, str) else prompt
        self.calls += 1
        return self.client.chat(self.model, messages, purpose="reflection", max_tokens=self.max_tokens)


def run_gepa(cfg, run_id, gen_client, judge_client, reflection_client, checker, runs_dir=ROOT / "runs", on_batch=None):
    spec = cfg["gepa"]["runs"][run_id]
    out_dir = runs_dir / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    adapter = FormalizerAdapter(cfg, spec["model"], gen_client, judge_client, checker, on_batch=on_batch)
    reflection = ReflectionLM(reflection_client, cfg["gepa"]["reflection_model"], cfg["gepa"]["reflection_max_tokens"])
    try:
        result = gepa.optimize(
            seed_candidate={COMPONENT: load_instructions(spec["seed_prompt"])},
            trainset=gepa_items("train"),
            valset=gepa_items("val"),
            adapter=adapter,
            reflection_lm=reflection,
            max_metric_calls=cfg["gepa"]["max_metric_calls"],
            seed=spec["seed"],
            run_dir=str(out_dir / "gepa"),
        )
    except (BudgetExceeded, AxleOutage) as e:
        (out_dir / "STOPPED").write_text(f"{type(e).__name__}: {e}\n")
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
