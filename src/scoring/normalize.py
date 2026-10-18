"""Normalize a candidate before any judge sees it: no comments, fixed name, `:= by sorry`.

Leading `set_option NAME VALUE in` lines (one reference needs `maxRecDepth`) are kept, one per line.
"""
import re

from src.scoring.strip import strip_comments

FIXED_NAME = "candidate"
OPTIONS = re.compile(r"^\s*((?:set_option\s+[\w.]+\s+\S+\s+in\s+)*)")
HEAD = re.compile(r"^\s*(?:set_option\s+[\w.]+\s+\S+\s+in\s+)*(?:@\[[^\]]*\]\s*)?(?:private\s+|protected\s+)?"
                  r"(?:theorem|lemma)\s+[^\s({\[:]+", re.DOTALL)
OPEN, CLOSE = "([{⟨⦃", ")]}⟩⦄"


def options_prefix(stmt):
    """The leading `set_option ... in` lines, normalized to one per line ('' if none)."""
    opts = re.findall(r"set_option\s+([\w.]+)\s+(\S+)\s+in", OPTIONS.match(stmt).group(1))
    return "".join(f"set_option {k} {v} in\n" for k, v in opts)


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
    stmt = HEAD.sub(f"{options_prefix(stmt)}theorem {FIXED_NAME}", stmt, count=1)
    end = signature_end(stmt)
    if end is None:
        return None
    return stmt[:end].rstrip() + " := by\n  sorry"
