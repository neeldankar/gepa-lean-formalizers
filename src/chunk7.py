"""Chunk 7: two exploratory analyses and the writeup number check.

Exploratory (labeled so wherever they appear):
- judge vs truth over GEPA's candidates: every candidate GEPA saved was scored on the 70 validation
  items with the optimization judge (its stored `score`, as GEPA saw it). Here the compiled outputs also
  get the final-eval truth label (certificate first, then the reference judge, with Deviation 4's re-ask).
- compile errors for arms A and B: each non-compiling test output is re-checked through AXLE and put in a
  bucket by its first Lean error.

The number check: every number in the writeup must be listed in numbers.json, and every listed number
with a source must equal that JSON value at the precision shown.
"""
import json
import re
from collections import Counter
from functools import reduce

from src.axle_check import OUTAGE
from src.scoring.compile import candidate_content
from src.scoring.normalize import normalize_statement
from src.scoring.score import truth_score


# --- judge vs truth over GEPA's candidates ---------------------------------------------------------

def candidate_files(run_dir):
    """[(candidate index, [validation rows])] in the order GEPA found the candidates."""
    order = [c["instructions"] for c in json.loads((run_dir / "candidates.json").read_text())["candidates"]]
    out = []
    for path in sorted((run_dir / "candidates").glob("*.jsonl")):
        lines = path.read_text().splitlines()
        out.append((order.index(json.loads(lines[0])["instructions"]), [json.loads(x) for x in lines[1:] if x.strip()]))
    return sorted(out, key=lambda c: c[0])


def candidate_truth_row(cfg, checker, client, run_id, cand, row, item):
    """One saved validation evaluation with a truth label added (compiled outputs only need the judges)."""
    out = {"run_id": run_id, "candidate": cand, "item_id": row["item_id"], "compiled": bool(row["compiled"]),
           "judge_score": row["score"], "truth_label": "unfaithful", "truth_source": "compile",
           "certified": False, "ref_verdict": None, "ref_missing": False}
    if not row["compiled"]:
        return out
    norm = normalize_statement(row["extracted"])
    prepared = {"extracted": row["extracted"], "normalized": norm, "format_failure": False, "format_reason": None,
                "compile_status": row["compile_status"], "compiled": True, "lean_errors": row["lean_errors"]}
    ts = truth_score(checker, client, cfg, item, None, prepared=prepared)
    out.update(normalized=norm, truth_label=ts["truth_label"], truth_source=ts["truth_source"],
               certified=bool(ts["certificate"] and ts["certificate"]["certified"]),
               ref_verdict=(ts["ref_judge"] or {}).get("verdict"), ref_reason=(ts["ref_judge"] or {}).get("reason"),
               ref_error_tag=(ts["ref_judge"] or {}).get("error_tag"), ref_missing=ts["ref_missing"],
               judge_missing=False)
    return out


def candidate_summary(rows):
    """{run_id: [{candidate, n, judge, truth, truth_missing, outages}]}: judge and truth in % of the items
    with a value (a missing truth label is left out of the truth denominator, as in the analysis)."""
    by = {}
    for r in rows:
        by.setdefault(r["run_id"], {}).setdefault(r["candidate"], []).append(r)
    out = {}
    for run_id, cands in sorted(by.items()):
        out[run_id] = []
        for cand, rs in sorted(cands.items()):
            truth = [r for r in rs if r["truth_label"] in ("faithful", "unfaithful")]
            out[run_id].append({"candidate": cand, "n": len(rs),
                                "judge": 100 * sum(r["judge_score"] for r in rs) / len(rs),
                                "truth": 100 * sum(r["truth_label"] == "faithful" for r in truth) / len(truth) if truth else None,
                                "truth_missing": sum(r["truth_label"] is None and r["truth_source"] != "outage" for r in rs),
                                "outages": sum(r["truth_source"] == "outage" for r in rs)})
    return out


# --- compile errors for arms A and B ---------------------------------------------------------------

BUCKETS = (
    ("unknown name", r"unknown (identifier|constant)|unknownIdentifier|unknownConstant"),
    ("type mismatch", r"type mismatch"),
    ("failed to synthesize instance", r"failed to synthesize"),
    ("syntax", r"unexpected token|expected '|unexpected end of input|unterminated"),
)


def error_bucket(status, errors):
    """The bucket of a non-compiling output: by its first Lean error, timeouts and resource limits apart."""
    if status in ("timeout", "resource"):
        return status
    first = errors[0] if errors else ""
    for name, pattern in BUCKETS:
        if re.search(pattern, first, re.IGNORECASE):
            return name
    return "other"


def compile_errors(rows, checker, items):
    """Non-compiling test outputs of the given rows: format failures counted apart, the rest re-checked
    and bucketed. Rows whose recheck status differs from the stored one are counted, not bucketed."""
    failed = [r for r in rows if r["dataset"] == "test" and r["compiled"] is False]
    to_check = [r for r in failed if r["normalized"]]
    results = checker.check_many([candidate_content(items[r["item_id"]], r["normalized"]) for r in to_check])
    out = {}
    for arm in sorted({r["arm"] for r in failed}):
        mine = [(r, res) for r, res in zip(to_check, results) if r["arm"] == arm]
        agree = [(r, res) for r, res in mine if res.status == r["compile_status"]]
        buckets = Counter(error_bucket(res.status, res.errors) for _, res in agree)
        n = sum(buckets.values())
        out[arm] = {"outputs": sum(r["arm"] == arm for r in rows if r["dataset"] == "test"),
                    "not_compiled": sum(r["arm"] == arm for r in failed),
                    "format_failures": sum(r["arm"] == arm and not r["normalized"] for r in failed),
                    "rechecked": len(mine), "recheck_status_differs": len(mine) - len(agree),
                    "recheck_outages": sum(res.status == OUTAGE for _, res in mine),
                    "buckets": {k: {"count": v, "share": 100 * v / n} for k, v in buckets.most_common()}}
    return out


# --- writeup number check --------------------------------------------------------------------------

NUMBER = re.compile(r"(?<![\w.,])[-+]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?(?!\w|\.\d|,\d)")
SKIP = re.compile(r"\]\([^)]*\)|https?://\S+|\b\d{4}\.\d{5}\b|\b\d{4}-\d{2}-\d{2}\b")  # links, URLs, arXiv ids, dates


def numbers_in(text):
    return NUMBER.findall(SKIP.sub(" ", text))


def lookup(data, path):
    return reduce(lambda d, k: d[int(k)] if isinstance(d, list) else d[k], path.split("."), data)


def shown(value, token):
    decimals = len(token.split(".")[1]) if "." in token else 0
    s = f"{value:,.{decimals}f}" if "," in token else f"{value:.{decimals}f}"
    return s.lstrip("-") if float(s.replace(",", "")) == 0 else s  # no "-0.0"


def check_numbers(text, entries, load):
    """entries: [{"value": "2.8", "source": "results.json", "path": "...", "scale": 1}] or
    [{"value": "95", "why": "..."}] for numbers that are not results. load(source) -> parsed JSON."""
    listed = {e["value"] for e in entries}
    unlisted = sorted({t.lstrip("+") for t in numbers_in(text)} - listed)
    wrong = []
    for e in entries:
        if "source" not in e:
            continue
        v = lookup(load(e["source"]), e["path"]) * e.get("scale", 1)
        got = shown(v, e["value"].lstrip("+"))
        if got != e["value"].lstrip("+"):
            wrong.append({**e, "actual": got})
    unused = sorted(listed - {t.lstrip("+") for t in numbers_in(text)})
    return {"ok": not unlisted and not wrong, "numbers": len(numbers_in(text)), "unlisted": unlisted, "wrong": wrong,
            "listed_not_in_text": unused}


def em_dashes(paths):
    """{path: count} of em dashes, only for files that have any."""
    return {str(p): c for p in paths if (c := p.read_text(errors="ignore").count("\u2014"))}
