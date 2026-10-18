"""Run the golden cases (tests/golden/cases.jsonl, train items only) through both scores."""
import json

from src.config import ROOT
from src.data.proofnet import ITEMS_PATH, read_jsonl
from src.scoring.score import judge_score, prepare, truth_score

CASES_PATH = ROOT / "tests/golden/cases.jsonl"


class RecordingClient:
    """Wraps an LLM client and keeps every prompt it sends, to check what judges saw."""

    def __init__(self, client):
        self.client = client
        self.prompts = []

    def chat(self, model, messages, **kwargs):
        self.prompts.extend(m["content"] for m in messages)
        return self.client.chat(model, messages, **kwargs)


def train_items():
    train = set(json.loads((ROOT / "data/splits.json").read_text())["train"])
    return {it["id"]: it for it in read_jsonl(ITEMS_PATH) if it["id"] in train}


def run_case(case, item, checker, client, cfg):
    rec = RecordingClient(client)
    p = prepare(checker, item, case["output"])
    js = judge_score(checker, rec, cfg, item, case["output"], prepared=p)
    ts = truth_score(checker, rec, cfg, item, case["output"], prepared=p)
    cert = ts["certificate"] or {}
    got = {
        "format_failure": p["format_failure"],
        "compiled": p["compiled"],
        "certified": cert.get("certified", False),
        "judge_verdict": (js["judge"] or {}).get("verdict"),
        "judge_score": js["judge_score"],
        "truth_label": ts["truth_label"],
        "normalized_contains": None,
        "never_reaches_judge": None,
        "r2c_discarded": bool(cert.get("discarded", {}).get("r2c")),
    }
    exp = case["expect"]
    if "normalized_contains" in exp:
        got["normalized_contains"] = exp["normalized_contains"] if exp["normalized_contains"] in (p["normalized"] or "") else "missing"
    if "never_reaches_judge" in exp:
        leaked = [s for s in exp["never_reaches_judge"] if any(s in q for q in rec.prompts)]
        got["never_reaches_judge"] = exp["never_reaches_judge"] if not leaked and rec.prompts else leaked or "judge never called"
    checks = {k: {"expected": v, "got": got[k], "ok": got[k] == v} for k, v in exp.items()}
    return {
        "case": case["case"], "item_id": case["item_id"], "passed": all(c["ok"] for c in checks.values()),
        "checks": checks, "normalized": p["normalized"], "compile_status": p["compile_status"],
        "lean_errors": p["lean_errors"][:2], "judge": js["judge"], "ref_judge": ts["ref_judge"],
        "certificate": ts["certificate"], "truth_source": ts["truth_source"],
    }


def run_golden(checker, client, cfg):
    items = train_items()
    results = []
    for case in read_jsonl(CASES_PATH):
        if case["item_id"] not in items:
            raise ValueError(f"golden case {case['case']!r} uses {case['item_id']}, which is not a train item")
        results.append(run_case(case, items[case["item_id"]], checker, client, cfg))
    return results
