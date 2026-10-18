"""Equivalence certificates (prereg Scoring, truth score step 2).

Both statements become closed propositions `∀ binders, conclusion`. For each direction we try a
fixed list of cheap tactics on `(hcert : source) : target`. A direction counts only if the same
tactic fails when `hcert` is replaced by `(hcert : True)`, so a target that automation proves
from scratch never counts. Both directions proved = certificate (faithful); otherwise unknown.

All attempts for one item go into one AXLE check; `failed_declarations` says which ones failed.
`Type*` and `Sort*` become `Type u` / `Sort u` with one shared universe so the two statements
can be instantiated at each other's types.
"""
import re

from src.scoring.compile import AUTOIMPLICIT_OFF
from src.scoring.normalize import HEAD, OPEN, CLOSE, signature_end

TACTICS = ["exact hcert", "simpa using hcert", "intros; simp_all", "intros; aesop", "intros; tauto"]
HEARTBEATS = 100000


def closed_prop(stmt):
    """`theorem n binders : concl := ...` -> `∀ binders, concl` (or `concl`). None if unparseable."""
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
            binders, concl = sig[:i].strip(), sig[i + 1:].strip()
            break
    else:
        return None
    prop = f"∀ {binders}, {concl}" if binders else concl
    return re.sub(r"\b(Type|Sort)\*", r"\1 u", prop)


def attempt_name(direction, k, with_hyp):
    return f"cert_{direction}_{k}_{'h' if with_hyp else 'noh'}"


def certificate_content(item, candidate, reference):
    """Lean file with every attempt, or None if either statement can't be turned into a prop."""
    c, r = closed_prop(candidate), closed_prop(reference)
    if c is None or r is None:
        return None
    decls = []
    for direction, (src, tgt) in {"c2r": (c, r), "r2c": (r, c)}.items():
        for k, tactic in enumerate(TACTICS):
            for with_hyp in (True, False):
                hyp = f"({src})" if with_hyp else "True"
                decls.append(
                    f"{AUTOIMPLICIT_OFF}set_option maxHeartbeats {HEARTBEATS} in\n"
                    f"theorem {attempt_name(direction, k, with_hyp)} (hcert : {hyp}) :\n    {tgt} := by\n  {tactic}"
                )
    parts = (item["header"], item["helper"], "universe u", *decls)
    return "\n\n".join(p for p in parts if p.strip())


def certificate(checker, item, candidate, reference):
    """Return {"certified": bool, "directions": {...}, "status": ...}. Outages pass through."""
    content = certificate_content(item, candidate, reference)
    if content is None:
        return {"certified": False, "status": "unparseable", "directions": {}}
    result = checker.check(content)
    if result.status not in ("ok", "lean_error"):
        return {"certified": False, "status": result.status, "directions": {}}
    failed = set(result.failed_declarations)
    if result.status == "lean_error" and not failed:
        return {"certified": False, "status": "lean_error", "directions": {}}
    directions, discarded = {}, {}
    for direction in ("c2r", "r2c"):
        with_hyp = [k for k in range(len(TACTICS)) if attempt_name(direction, k, True) not in failed]
        directions[direction] = [TACTICS[k] for k in with_hyp if attempt_name(direction, k, False) in failed]
        # proved, but also proved from scratch: the hypothesis-removal check throws these out
        discarded[direction] = [TACTICS[k] for k in with_hyp if attempt_name(direction, k, False) not in failed]
    return {"certified": all(directions.values()), "status": "ok", "directions": directions, "discarded": discarded}
