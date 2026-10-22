"""Block 2 numbers from summary.json (project, agree, armf steps) and the arm F probe files. Writes runs/chunk4/block2_numbers.json."""
import json
from pathlib import Path
d = Path(__file__).parent
s = json.loads((d / "summary.json").read_text())
cfg_rate = s["pod"]["usd_per_hour"]
m, p, o = s["measurements"], s["projection"], s["go_info"]["overnight_hours"]
lo, hi = m["reflections_per_run_bounds"]
out = {
    "go": s["go"], "agree": s["agree"],
    "reflections_per_run": {"pilot_accept_rate": m["accept_rate"], "expected": m["reflections_per_run"], "all_accepted": lo, "none_accepted": hi},
    "reflection": {"sample_calls": m["reflection_sample"], "median_s": m["reflection_median_s"], "slowest_s": m["reflection_slowest_s"],
                   "usd_per_call": m["reflection_usd"],
                   "usd_six_runs": {"expected": 6 * m["reflections_per_run"] * m["reflection_usd"], "low": 6 * lo * m["reflection_usd"], "high": 6 * hi * m["reflection_usd"]}},
    "overnight_hours": o, "gepa_serial_gpu_hours_upper": p["gepa_gpu_usd_serial"] / cfg_rate,
    "projection_usd": {k: p[k] for k in ("chunk5_usd_parallel", "chunk5_usd_serial", "total_usd_parallel", "total_usd_upper", "spent_usd", "arm_f_usd")},
    "arm_f_glm53": s["armf"], "arm_f_glm53_nothink_probe": json.loads((d / "arm_f_glm53_nothink_probe.json").read_text()),
    "qwen_a3_truth_faithful": s["stats"]["qwen_a3"]["truth_faithful_rate"], "reform_truth_faithful": s["stats"]["reform"]["truth_faithful_rate"],
}
(d / "block2_numbers.json").write_text(json.dumps(out, indent=1) + "\n")
print(json.dumps({k: out[k] for k in ("reflections_per_run", "reflection", "gepa_serial_gpu_hours_upper", "projection_usd")}, indent=1))
