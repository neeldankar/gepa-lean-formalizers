"""Chunk 7: two exploratory analyses and the writeup number check.

Exploratory (labeled so wherever they appear):
- judge vs truth over GEPA's candidates: every candidate GEPA saved was scored on the 70 validation
  items with the optimization judge (its stored `score`, as GEPA saw it). Here the compiled outputs also
  get the final-eval truth label (certificate first, then the reference judge, with Deviation 4's re-ask).
- compile errors for arms A and B: each non-compiling test output is re-checked through AXLE and put in a
  bucket by its first Lean error.
- the judge-minus-truth gap over GEPA iterations: a within-run slope pooled per model, with an item bootstrap.
- Mathlib names in the six optimized prompts: each name checked with AXLE, and whether the prompt warns
  against it or recommends it.

The number check: every number in the writeup must be listed in numbers.json, and every listed number
with a source must equal that JSON value at the precision shown.
"""
import json
import re
from collections import Counter
from functools import reduce

import numpy as np

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


def candidate_iterations(run_dir):
    """{candidate index: x}: 0 for the seed prompt, i + 1 for a candidate proposed at GEPA iteration i."""
    log = json.loads((run_dir / "gepa/run_log.json").read_text())
    return {0: 0, **{p: e["i"] + 1 for e in log for p in (e.get("new_program_indices") or [])}}


def _slope(x, gaps, groups):
    """Within-group OLS slope of gaps on x (one common slope, an intercept per group); gaps may be 2-D
    (candidates x resamples)."""
    xd, gd = x.astype(float).copy(), gaps.astype(float).copy()
    for g in np.unique(groups):
        m = groups == g
        xd[m] -= xd[m].mean()
        gd[m] -= gd[m].mean(axis=0)
    return (xd @ gd) / (xd @ xd)


def gap_slope(rows, iters, n_boot, seed, exclude=()):
    """Slope of (judge score minus truth score), in points per GEPA iteration, pooled within run.

    rows: candidate-truth rows of one model; iters: {run_id: {candidate: x}}; exclude: candidate indices
    left out. Each resample draws the validation items with replacement, the same draw for every candidate."""
    cells = {}
    for r in rows:
        if r["candidate"] not in exclude:
            cells.setdefault((r["run_id"], r["candidate"]), {})[r["item_id"]] = r["judge_score"] - (r["truth_label"] == "faithful")
    keys = sorted(cells)
    items = sorted({i for c in cells.values() for i in c})
    d = 100 * np.array([[cells[k][i] for i in items] for k in keys])
    x = np.array([iters[run][cand] for run, cand in keys])
    groups = np.array([run for run, _ in keys])
    idx = np.random.default_rng(seed).integers(0, len(items), (n_boot, len(items)))
    boot = _slope(x, d[:, idx].mean(axis=2), groups)
    lo, hi = np.percentile(boot, [2.5, 97.5])
    return {"slope": float(_slope(x, d.mean(axis=1), groups)), "ci": [float(lo), float(hi)],
            "candidates": len(keys), "mean_gap": float(d.mean()), "max_x": int(x.max())}


# --- Mathlib names in the optimized prompts ---------------------------------------------------------

IDENT = re.compile(r"(?<![\w.'@\\])@?([A-Za-z_][\w']*(?:\.[A-Za-z_][\w']*)*)")
KEYWORDS = {"theorem", "lemma", "def", "fun", "by", "sorry", "import", "open", "scoped", "Type", "Prop", "Sort",
            "have", "show", "let", "in", "at", "with", "then", "else", "if", "match", "where", "from", "set_option",
            "autoImplicit", "Mathlib", "local", "notation", "variable", "example", "true", "false", "theorem_name"}
PLACEHOLDERS = {"IsX", "Foo.bar", "Namespace.foo"}  # the prompts' own placeholder names, not claims about Mathlib
SPANS = r"((?:`X+`(?:\s*(?:,|/|\bor\b|\band\b)\s*)?)+)"  # a list of (masked) backtick spans
# a nonexistence claim: "no `X`", "an invented `X`", "no guessed names (`X`", "invent classes like `X`",
# or "`X`, `Y` do NOT exist"
# ("NOT `X`" is left out: "NOT `ContinuousOn`" or "NOT `x ^ n = 1`" are about meaning, not existence)
WARN_BEFORE = re.compile(r"(?:\b(?:no|NO)|nonexistent|invented|invent\w* (?:\w+ )?like)\s+(?:an? |the )?(?:invented |nonexistent |guessed \w+ \(?)?"
                         + SPANS + r"(?![\s`X/,]*(?:unless|typeclass failure))")
WARN_AFTER = re.compile(SPANS + r"\s*(?:\u2014|-|,)?\s*(?:(?:do|does|are|is) (?:NOT|not) (?:exist|real)|(?:don't|doesn't) exist|neither exists)")
UNKNOWN = re.compile(r"Unknown (?:constant|identifier) `?([\w.']+)")
CLAUSE = re.compile(r"Good:|→|;|(?<=[.)])\s+(?=[A-Z(`])")
BINDER = re.compile(r"(?:[(\[{⦃]|∀|∃|fun|λ)\s*((?:[^\s:(){}\[\],]+\s+)*[^\s:(){}\[\],]+)\s*:")
DEFINED = re.compile(r"(?:theorem|lemma|def|abbrev|structure|class|inductive|instance)\s+([^\s:({\[]+)")


def mathlib_like(tok):
    """A namespaced name (first part capitalized, 2+ characters, so not a field of a variable `T.adj`), a
    capitalized name of 2+ characters, or a lowercase name of 4+ characters with camelCase or an underscore.
    Bound variables and the items' own definitions are dropped by the caller."""
    if tok in KEYWORDS or tok in PLACEHOLDERS or not tok.isascii() or tok.isupper() and len(tok) > 2:
        return False
    if "." in tok:
        return tok[0].isupper() and len(tok.split(".")[0]) >= 2
    return (tok[0].isupper() and len(tok) >= 2) or (len(tok) >= 4 and (any(c.isupper() for c in tok) or "_" in tok))


def defined_names(text):
    return set(DEFINED.findall(text)) | set(re.findall(r'notation\s+"([^"]+)"', text))


def prompt_names(text, exclude=frozenset()):
    """{name: {"roles": {...}, "lines": [line, ...]}} for the names in backtick spans and fenced code blocks
    (Lean comments dropped). Role by the clause the span sits in: "warned" when it says the name does not
    exist (WARN_BEFORE, WARN_AFTER, or an "Unknown constant" message);
    "error_example" on the Bad side of a Bad/Good pair or in a clause about a failure; otherwise "recommended".
    Binders, theorem names and `exclude` (the items' own definitions) are left out."""
    out = {}
    lines = text.splitlines()
    in_block = False
    for line in lines:
        if line.strip().startswith("```"):
            in_block = not in_block
            continue
        line = line.replace("```", "   ")  # a fence mentioned mid-sentence is not a span
        spans = [(line, None)] if in_block else [(m.group(1), m.start()) for m in re.finditer(r"`([^`]+)`", line)]
        # clause separators and warnings outside the spans (a span's own arrows and semicolons don't split it)
        masked = re.sub(r"`([^`]+)`", lambda m: "`" + "X" * len(m.group(1)) + "`", line)
        seps = [m.span() for m in CLAUSE.finditer(masked)]
        before = [m.span(1) for m in WARN_BEFORE.finditer(masked)]
        after = [m.span(1) for m in WARN_AFTER.finditer(masked)]
        for span, pos in spans:
            skip = defined_names(span) | {n for b in BINDER.findall(span) for n in b.split()}
            role = "recommended"
            if pos is not None:
                start = max([e for _, e in seps if e <= pos], default=0)
                end = min([b for b, _ in seps if b > pos], default=len(line))
                clause = masked[start:end]
                if any(a <= pos < b for a, b in before + after):
                    role = "warned"
                elif "Bad:" in clause or re.search(r"\bfail", clause, re.IGNORECASE):
                    role = "error_example"
            unknown = set(UNKNOWN.findall(span))
            for tok in IDENT.findall(re.sub(r"--.*|Unknown (?:constant|identifier)", "", span)):
                if mathlib_like(tok) and tok not in skip and tok not in exclude:
                    e = out.setdefault(tok, {"roles": set(), "lines": []})
                    e["roles"].add("warned" if tok in unknown else role)
                    if line.strip() not in e["lines"]:
                        e["lines"].append(line.strip())
    return out


def name_check_contents(name, opens):
    """Three ways a name can exist: a constant, a constant under the items' opens, a namespace."""
    return [f"import Mathlib\n\n#check @{name}\n", f"import Mathlib\n\n{opens}\n\n#check @{name}\n",
            f"import Mathlib\n\nopen {name} in\nexample : True := trivial\n"]


# --- compile errors for arms A and B ---------------------------------------------------------------

BUCKETS = (
    ("unknown name", r"unknown (identifier|constant)|unknownIdentifier|unknownConstant|invalid field"),
    ("type mismatch", r"type mismatch"),
    ("type or function expected", r"type expected|function expected"),
    ("failed to synthesize instance", r"failed to synthesize|typeclass instance problem is stuck"),
    ("syntax", r"unexpected token|expected '|expected token|unexpected end of input|unterminated"),
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
        outputs = sum(r["arm"] == arm for r in rows if r["dataset"] == "test")
        out[arm] = {"outputs": outputs,
                    "not_compiled": sum(r["arm"] == arm for r in failed),
                    "format_failures": sum(r["arm"] == arm and not r["normalized"] for r in failed),
                    "rechecked": len(mine), "recheck_status_differs": len(mine) - len(agree),
                    "recheck_outages": sum(res.status == OUTAGE for _, res in mine),
                    "buckets": {k: {"count": v, "share": 100 * v / n, "share_of_outputs": 100 * v / outputs}
                                for k, v in buckets.most_common()}}
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
