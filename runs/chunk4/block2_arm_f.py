"""Block 2 arm F options: cost projections from raw cost rows and the pilot rows. Writes runs/chunk4/block2_arm_f_options.json."""
import gzip, json, statistics, sys
from pathlib import Path
import yaml
root = Path(sys.argv[1])
cfg = yaml.safe_load(open(root / "config.yaml"))
costs = [json.loads(l) for l in open(root / "runs/costs.jsonl")]
kimi = [r for r in costs if r["purpose"] == "generate" and r["model"] == "moonshotai/Kimi-K3"]
out_tok = [r["completion_tokens"] for r in kimi]
in_tok = statistics.mean(r["prompt_tokens"] for r in kimi)
cap16, cap32, n_test = cfg["generation"]["max_tokens"], 32768, 247
hit = sum(t >= cap16 for t in out_tok)
under = [t for t in out_tok if t < cap16]
price = lambda m, i, o: (i * cfg["llm"]["prices"][m]["input"] + o * cfg["llm"]["prices"][m]["output"]) / 1e6
glm = {"input": 1.40, "output": 4.40}  # zai-org/GLM-5.3 on Together, third-party trackers, 2026-10-22; not in config
glm_price = lambda i, o: (i * glm["input"] + o * glm["output"]) / 1e6
mean_all, mean_under = statistics.mean(out_tok), statistics.mean(under)
p_hit = hit / len(out_tok)
# ReForm-8B outputs that hit the 16k cap in the pilot (Qwen3-8B thinking off never came close)
reform = [json.loads(l) for l in gzip.open(root / "runs/chunk4/pilot_reform.jsonl.gz", "rt")] if (root / "runs/chunk4/pilot_reform.jsonl.gz").exists() else []
summary = json.load(open(root / "runs/chunk4/summary.json"))["stats"]
res = {
    "observed_arm_f_kimi_k3": {"calls": len(out_tok), "completion_tokens": out_tok, "mean_prompt_tokens": round(in_tok),
                              "hit_16k_cap": hit, "mean_completion_tokens": round(mean_all), "mean_completion_tokens_under_cap": round(mean_under),
                              "usd_logged": round(sum(r["usd"] for r in kimi), 3)},
    "test_items": n_test,
    "status_quo_16k_kimi": {"expected_usd": round(n_test * ((1 - p_hit) * price("moonshotai/Kimi-K3", in_tok, mean_under) + p_hit * price("moonshotai/Kimi-K3", in_tok, cap16)), 2),
                            "worst_usd": round(n_test * price("moonshotai/Kimi-K3", in_tok, cap16), 2),
                            "expected_items_cut_off": round(n_test * p_hit)},
    "a_32k_all_arms": {"arm_f_expected_usd_if_cut_off_items_run_to_32k": round(n_test * ((1 - p_hit) * price("moonshotai/Kimi-K3", in_tok, mean_under) + p_hit * price("moonshotai/Kimi-K3", in_tok, cap32)), 2),
                       "arm_f_worst_usd": round(n_test * price("moonshotai/Kimi-K3", in_tok, cap32), 2),
                       "reform_pilot_hit_16k": summary["reform"]["hit_length_cap"], "reform_pilot_outputs": summary["reform"]["outputs"],
                       "qwen_nothink_pilot_max_tokens": max(summary[k]["tokens_max"] for k in ("qwen_nothink", "qwen_a2", "qwen_a3"))},
    "b_16k_glm_5_3": {"price_per_1m": glm, "expected_usd_if_kimi_like_tokens": round(n_test * glm_price(in_tok, mean_all), 2),
                      "worst_usd": round(n_test * glm_price(in_tok, cap16), 2)},
    "c_drop_arm_f": {"usd": 0},
    "prereg_budget_line_arm_f_usd": 10,
}
(root / "runs/chunk4/block2_arm_f_options.json").write_text(json.dumps(res, indent=1) + "\n")
print(json.dumps(res, indent=1))
