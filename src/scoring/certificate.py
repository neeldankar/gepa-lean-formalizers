"""Equivalence certificates (prereg Scoring, truth score step 2; Changes, items 10 and 12).

Each direction gets its own Lean file that declares only its hypothesis-side statement as a
sorried theorem, so no tactic can close the goal by citing the target's own theorem:
  c2r: `cert_cand` (candidate, autoImplicit off) proves the reference's closed prop
       (`∀ binders, conclusion`, elaborated as ProofNet-Verified ships it, autoImplicit on).
  r2c: `cert_ref` (reference as shipped) proves the candidate's closed prop (autoImplicit off).
Tactics name the hypothesis theorem `H` directly, so every use gets fresh universe levels.
A direction counts only if the same tactic fails with `H` = `cert_true : True`, so a target that
automation proves from scratch never counts. Both directions = certificate (faithful); anything
else = unknown.

Every attempt depends on a sorried theorem, so AXLE lists them all in `failed_declarations`;
an attempt succeeded iff no Lean error falls inside its own lines.
"""
import re

from src.scoring.compile import AUTOIMPLICIT_OFF
from src.scoring.normalize import CLOSE, HEAD, OPEN, options_prefix, signature_end

TACTICS = [
    "exact @{H}",
    "intros; apply {H} <;> assumption",
    "intros; simp_all [{H}]",
    "intros; aesop (add unsafe 50% apply {H})",
    "intros; have hcert := @{H}; tauto",
]
HEARTBEATS = 100000
NO_HYP = "cert_true"
DIRECTIONS = ("c2r", "r2c")


def split_signature(stmt):
    """(binders, conclusion) of `theorem n binders : concl := ...`, or None."""
    m = HEAD.match(stmt)
    end = signature_end(stmt)
    if not m or end is None:
        return None
    sig = stmt[m.end():end].strip()
    depth = 0
    for i, ch in enumerate(sig):
        if ch in OPEN:
            depth += 1
        elif ch in CLOSE:
            depth -= 1
        elif ch == ":" and depth == 0 and not sig.startswith(":=", i):
            return sig[:i].strip(), sig[i + 1:].strip()
    return None


def closed_prop(stmt):
    parts = split_signature(stmt)
    if parts is None:
        return None
    binders, concl = parts
    return f"∀ {binders}, {concl}" if binders else concl


def sorried_theorem(stmt, name):
    binders, concl = split_signature(stmt)
    return f"{options_prefix(stmt)}theorem {name} {binders} :\n    {concl} := by\n  sorry"


def attempt_name(direction, k, with_hyp):
    return f"cert_{direction}_{k}_{'h' if with_hyp else 'noh'}"


def direction_content(item, direction, candidate, reference):
    """(Lean text, {attempt name: (first line, last line)}), or None if a statement won't parse."""
    if split_signature(candidate) is None or split_signature(reference) is None:
        return None
    if direction == "c2r":
        hyp_name, hyp_decl = "cert_cand", AUTOIMPLICIT_OFF + sorried_theorem(candidate, "cert_cand")
        target, prefix = closed_prop(reference), ""
    else:
        hyp_name, hyp_decl = "cert_ref", sorried_theorem(reference, "cert_ref")
        target, prefix = closed_prop(candidate), AUTOIMPLICIT_OFF
    # options a statement needs (e.g. maxRecDepth) apply wherever its proposition is elaborated
    opts = "".join(dict.fromkeys((options_prefix(candidate) + options_prefix(reference)).splitlines(keepends=True)))
    blocks = [b for b in (item["header"], item["helper"], hyp_decl, f"theorem {NO_HYP} : True := trivial") if b.strip()]
    attempts = {}
    for k, tactic in enumerate(TACTICS):
        for with_hyp in (True, False):
            name = attempt_name(direction, k, with_hyp)
            proof = tactic.format(H=hyp_name if with_hyp else NO_HYP)
            attempts[name] = f"{prefix}{opts}set_option maxHeartbeats {HEARTBEATS} in\ntheorem {name} :\n    {target} := by\n  {proof}"
    spans, line = {}, 1
    for b in blocks:
        line += b.count("\n") + 2  # the block plus the blank line after it
    for name, block in attempts.items():
        spans[name] = (line, line + block.count("\n"))
        line += block.count("\n") + 2
    return "\n\n".join(blocks + list(attempts.values())), spans


def error_lines(errors):
    """Line number of each Lean error (`-:LINE:COL...`); None for an error without one."""
    return [int(m.group(1)) if (m := re.match(r"-:(\d+):", e)) else None for e in errors]


def run_direction(checker, item, direction, candidate, reference):
    """{"status", "ok": set of attempts that elaborated without error}."""
    built = direction_content(item, direction, candidate, reference)
    if built is None:
        return {"status": "unparseable", "ok": set()}
    text, spans = built
    result = checker.check(text)
    if result.status not in ("ok", "lean_error"):
        return {"status": result.status, "ok": set()}
    lines = error_lines(result.errors)
    first_attempt = min(a for a, _ in spans.values())
    if any(n is None or n < first_attempt for n in lines):
        return {"status": "setup_error", "ok": set()}  # header, helper or hypothesis theorem failed
    ok = {name for name, (a, b) in spans.items() if not any(a <= n <= b for n in lines)}
    return {"status": "ok", "ok": ok}


def certificate(checker, item, candidate, reference):
    """Return {"certified", "status", "directions", "discarded"}. Outages pass through as status."""
    directions, discarded = {}, {}
    for d in DIRECTIONS:
        run = run_direction(checker, item, d, candidate, reference)
        if run["status"] != "ok":
            return {"certified": False, "status": run["status"], "directions": {}, "discarded": {}}
        with_hyp = [k for k in range(len(TACTICS)) if attempt_name(d, k, True) in run["ok"]]
        directions[d] = [TACTICS[k] for k in with_hyp if attempt_name(d, k, False) not in run["ok"]]
        # proved, but also proved from scratch: the hypothesis-removal check throws these out
        discarded[d] = [TACTICS[k] for k in with_hyp if attempt_name(d, k, False) in run["ok"]]
    return {"certified": all(directions.values()), "status": "ok", "directions": directions, "discarded": discarded}
