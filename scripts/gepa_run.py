"""Chunk 5 (and the pilot): one GEPA run on the pod.

Usage: python -m scripts.gepa_run RUN_ID [--chunk N]   (RUN_ID from config.yaml gepa.runs)
"""
import json
import sys

from src.axle_check import AxleChecker
from src.config import load_config
from src.costs import GpuMeter
from src.generate import formalizer_client
from src.llm import LLMClient
from src.runner import run_gepa


def main(argv):
    run_id = argv[0]
    chunk = int(argv[argv.index("--chunk") + 1]) if "--chunk" in argv else 5
    cfg = load_config()
    spec = cfg["gepa"]["runs"][run_id]
    gen = formalizer_client(cfg, spec["model"], chunk, run_id=run_id)
    judge = LLMClient(cfg, chunk, run_id=run_id)
    meter = GpuMeter(cfg, chunk, run_id)
    result = run_gepa(cfg, run_id, gen, judge, judge, AxleChecker(cfg["axle"]), on_batch=meter.tick)
    meter.tick()
    print(json.dumps(result))
    sys.exit(0 if result["status"] == "done" else 1)


if __name__ == "__main__":
    main(sys.argv[1:])
