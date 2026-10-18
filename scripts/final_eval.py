"""Chunk 5: final evaluation of every arm. Refuses to run until all six GEPA runs are DONE.

Usage: python -m scripts.final_eval [ARM ...]   (default: all arms in config.yaml)
Writes runs/final/<arm>.jsonl.gz. Exits 1 if any row hit an AXLE outage (rerun to fill it).
"""
import sys

from src.axle_check import AxleChecker
from src.config import ROOT, load_config
from src.final_eval import eval_arm, write_rows
from src.generate import formalizer_client
from src.llm import LLMClient
from src.scoring import memorization

CHUNK = 5


def main():
    cfg = load_config()
    checker = AxleChecker(cfg["axle"])
    judge = LLMClient(cfg, CHUNK, run_id="final")
    index = memorization.load_index()
    outages = 0
    for arm in sys.argv[1:] or list(cfg["arms"]):
        gen = formalizer_client(cfg, cfg["arms"][arm]["model"], CHUNK, run_id=f"final_{arm}")
        rows = eval_arm(cfg, arm, gen, judge, checker, ROOT / "runs", ROOT, mem_index=index)
        write_rows(ROOT / "runs/final" / f"{arm}.jsonl.gz", rows)
        outages += sum(r["outage"] for r in rows)
        print(f"arm {arm}: {len(rows)} rows, {sum(r['outage'] for r in rows)} outages")
    sys.exit(1 if outages else 0)


if __name__ == "__main__":
    main()
