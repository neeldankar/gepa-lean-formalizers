"""Judge score and truth score for one model output.

Shared first stage (`prepare`): extract -> normalize (no comments, fixed name, `:= by sorry`) ->
compile with autoImplicit off. Judges only ever see the normalized statement.

Judge score = 1 iff compiled and the optimization judge says faithful.
Truth label = certificate if there is one, else the reference judge's verdict (judge runs on
every compiled item). A compile failure is unfaithful. AXLE outages are returned as `outage`
and must not be scored. A judge reply still unparseable after one re-ask is missing: judge score
None (`judge_missing`), or truth label None (`ref_missing`, unless a certificate settles it).
"""
from src.axle_check import OK, OUTAGE
from src.scoring import judge
from src.scoring.certificate import certificate
from src.scoring.compile import compile_candidate
from src.scoring.extract import extract_statement
from src.scoring.normalize import normalize_statement


def prepare(checker, item, raw_output):
    stmt, reason = extract_statement(raw_output)
    out = {"extracted": stmt, "normalized": None, "format_failure": stmt is None,
           "format_reason": reason, "compile_status": None, "compiled": False, "lean_errors": []}
    if stmt is None:
        return out
    norm = normalize_statement(stmt)
    if norm is None:
        out.update(format_failure=True, format_reason="no `theorem ... :=` after normalizing")
        return out
    result = compile_candidate(checker, item, norm)
    out.update(normalized=norm, compile_status=result.status, compiled=result.status == OK, lean_errors=result.errors)
    return out


def judge_score(checker, client, cfg, item, raw_output, prepared=None):
    p = prepared or prepare(checker, item, raw_output)
    out = {**p, "judge": None, "judge_score": 0, "judge_missing": False}
    if p["compile_status"] == OUTAGE:
        out["judge_score"] = None
        return out
    if p["compiled"]:
        out["judge"] = judge.optimization_judge(client, cfg, item["informal_stmt"], p["normalized"])
        if judge.is_missing(out["judge"]["verdict"]):
            out.update(judge_score=None, judge_missing=True)
        else:
            out["judge_score"] = int(out["judge"]["verdict"] == "faithful")
    return out


def truth_score(checker, client, cfg, item, raw_output, prepared=None):
    p = prepared or prepare(checker, item, raw_output)
    out = {**p, "certificate": None, "ref_judge": None, "truth_label": "unfaithful", "truth_source": "compile",
           "ref_missing": False}
    if p["compile_status"] == OUTAGE:
        out.update(truth_label=None, truth_source="outage")
        return out
    if not p["compiled"]:
        if p["format_failure"]:
            out["truth_source"] = "format"
        return out
    reference = normalize_statement(item["formal_stmt"])
    if cfg["scoring"]["certificates"]:
        out["certificate"] = certificate(checker, item, p["normalized"], reference)
        if out["certificate"]["status"] == OUTAGE:
            out.update(truth_label=None, truth_source="outage")
            return out
    out["ref_judge"] = judge.reference_judge(client, cfg, item["informal_stmt"], reference, p["normalized"])
    out["ref_missing"] = judge.is_missing(out["ref_judge"]["verdict"])
    if out["certificate"] and out["certificate"]["certified"]:
        out.update(truth_label="faithful", truth_source="certificate")
    elif out["ref_missing"]:
        out.update(truth_label=None, truth_source="ref_judge_missing")
    else:
        verdict = out["ref_judge"]["verdict"]
        out.update(truth_label="faithful" if verdict == "faithful" else "unfaithful", truth_source="ref_judge")
    return out
