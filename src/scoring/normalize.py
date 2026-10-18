"""Normalize a candidate before any judge sees it: no comments, fixed name, `:= by sorry`."""
import re

from src.scoring.strip import strip_comments

FIXED_NAME = "candidate"
HEAD = re.compile(r"^\s*(?:@\[[^\]]*\]\s*)?(?:private\s+|protected\s+)?(?:theorem|lemma)\s+[^\s({\[:]+", re.DOTALL)
OPEN, CLOSE = "([{⟨⦃", ")]}⟩⦄"


def signature_end(stmt):
    """Index of the first `:=` outside brackets (where the proof starts), or None."""
    depth = 0
    for i, ch in enumerate(stmt):
        if ch in OPEN:
            depth += 1
        elif ch in CLOSE:
            depth -= 1
        elif depth == 0 and stmt.startswith(":=", i):
            return i
    return None


def normalize_statement(stmt):
    """Return the normalized statement, or None if it isn't a theorem with a `:=`."""
    stmt = strip_comments(stmt)
    if not HEAD.match(stmt):
        return None
    stmt = HEAD.sub(f"theorem {FIXED_NAME}", stmt, count=1)
    end = signature_end(stmt)
    if end is None:
        return None
    return stmt[:end].rstrip() + " := by\n  sorry"
