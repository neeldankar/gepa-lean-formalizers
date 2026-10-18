"""Chunk 6: the frozen analysis. Reads runs/final/*.jsonl.gz and, if present, the hand labels.

Usage: python -m scripts.analyze [--labels runs/handcheck/labels.csv --sample runs/handcheck/sample.jsonl]
Writes results.json and figures/ at the repo root.
"""
import json
import sys

from src.analysis import analyze, figures, read_labels
from src.config import ROOT, load_config
from src.final_eval import read_rows


def main(argv):
    cfg = load_config()
    rows = [r for path in sorted((ROOT / "runs/final").glob("*.jsonl.gz")) for r in read_rows(path)]
    labeled = None
    if "--labels" in argv:
        labeled = read_labels(argv[argv.index("--labels") + 1], argv[argv.index("--sample") + 1])
    results = analyze(rows, cfg, labeled)
    (ROOT / "results.json").write_text(json.dumps(results, indent=1) + "\n")
    figures(results, ROOT / "figures")
    print(json.dumps(results["confirmatory"]["contrasts"], indent=1))


if __name__ == "__main__":
    main(sys.argv[1:])
