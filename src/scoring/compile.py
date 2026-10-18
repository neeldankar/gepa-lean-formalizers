"""Compile a candidate statement in its item's context, with autoImplicit off (prereg Changes, item 10).

The judge score, the truth score and the certificates all build their Lean code here.
"""
AUTOIMPLICIT_OFF = "set_option autoImplicit false in\n"


def candidate_content(item, stmt):
    """Header, helper definitions, then the statement with autoImplicit off for that one command."""
    parts = (item["header"], item["helper"], AUTOIMPLICIT_OFF + stmt.strip())
    return "\n\n".join(p for p in parts if p.strip())


def compile_candidate(checker, item, stmt):
    return checker.check(candidate_content(item, stmt))
