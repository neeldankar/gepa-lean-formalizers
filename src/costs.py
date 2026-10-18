"""GPU cost logging and cost summaries. API calls are logged by src/llm.py into the same file."""
import json
import time
from datetime import datetime, timezone

from src.llm import COSTS_PATH, BudgetExceeded, spent


class GpuMeter:
    """Logs pod time as cost rows (`purpose: gpu`) and stops the run at the chunk's cap."""

    def __init__(self, cfg, chunk, run_id, costs_path=COSTS_PATH, clock=time.monotonic):
        self.rate = cfg["gpu"]["usd_per_hour"]
        self.cap = cfg["budget"]["chunk_caps_usd"][chunk]
        self.chunk, self.run_id, self.costs_path, self.clock = chunk, run_id, costs_path, clock
        self.last = clock()

    def tick(self):
        now = self.clock()
        hours, self.last = (now - self.last) / 3600, now
        with open(self.costs_path, "a") as f:
            f.write(json.dumps({
                "time": datetime.now(timezone.utc).isoformat(timespec="seconds"), "chunk": self.chunk,
                "run_id": self.run_id, "purpose": "gpu", "model": "pod", "prompt_tokens": 0,
                "completion_tokens": 0, "usd": hours * self.rate, "hours": hours,
            }) + "\n")
        if spent(self.chunk, self.costs_path) >= self.cap:
            raise BudgetExceeded(f"chunk {self.chunk} reached its ${self.cap} cap")


def summarize(rows):
    """Totals by chunk, run and purpose."""
    out = {"usd_total": 0.0, "by_chunk": {}, "by_run": {}, "by_purpose": {}}
    for r in rows:
        out["usd_total"] += r["usd"]
        for key, name in (("by_chunk", str(r["chunk"])), ("by_run", r.get("run_id") or "-"), ("by_purpose", r["purpose"])):
            d = out[key].setdefault(name, {"calls": 0, "usd": 0.0})
            d["calls"] += 1
            d["usd"] += r["usd"]
    return out
