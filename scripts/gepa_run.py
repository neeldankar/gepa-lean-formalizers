"""Chunk 5 (and the pilot): one GEPA run on the pod.

Usage: python -m scripts.gepa_run RUN_ID [--chunk N] [--no-gpu-meter] [--runs-dir DIR] [--override JSON]
  RUN_ID from config.yaml gepa.runs. --no-gpu-meter: the chunk 5 combined job meters the pod once for all
  six runs. --runs-dir and --override (merged into the run's spec): the combined job's dry run only.
"""
import json
import sys

from src.axle_check import AxleChecker
from src.config import ROOT, load_config
from src.costs import GpuMeter
from src.generate import formalizer_client
from src.llm import LLMClient
from src.runner import run_gepa


def main(argv):
    run_id = argv[0]
    chunk = int(argv[argv.index("--chunk") + 1]) if "--chunk" in argv else 5
    cfg = load_config()
    if "--override" in argv:
        cfg["gepa"]["runs"][run_id].update(json.loads(argv[argv.index("--override") + 1]))
    runs_dir = ROOT / argv[argv.index("--runs-dir") + 1] if "--runs-dir" in argv else ROOT / "runs"
    run(cfg, run_id, chunk, runs_dir=runs_dir, meter="--no-gpu-meter" not in argv)


def run(cfg, run_id, chunk, runs_dir=ROOT / "runs", meter=True):
    spec = cfg["gepa"]["runs"][run_id]
    gen = formalizer_client(cfg, spec["model"], chunk, run_id=run_id)
    judge = LLMClient(cfg, chunk, run_id=run_id)
    meter = GpuMeter(cfg, chunk, run_id) if meter else None
    result = run_gepa(cfg, run_id, gen, judge, judge, AxleChecker(cfg["axle"]), runs_dir=runs_dir,
                      on_batch=meter.tick if meter else None)
    if meter:
        meter.tick()
    print(json.dumps(result))
    sys.exit(0 if result["status"] == "done" else 1)


if __name__ == "__main__":
    main(sys.argv[1:])
