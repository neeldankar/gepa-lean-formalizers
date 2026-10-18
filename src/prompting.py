"""Build the formalizer's user message. GEPA only ever edits `instructions`.

Every arm: instructions, newline, English statement, newline (arm C's first part is exactly
ReForm-8B's released prompt, prereg Changes item 11), then one fixed block with the item's Lean
header and helper definitions.
"""
from src.config import ROOT

CONTEXT = "\nLean 4 context (use these imports, opens and definitions; write one theorem):\n```lean4\n{context}\n```\n"


def load_instructions(path):
    return (ROOT / path).read_text().rstrip("\n")


def user_message(instructions, item):
    context = "\n\n".join(p for p in (item["header"], item["helper"]) if p.strip())
    return f"{instructions}\n{item['informal_stmt']}\n" + CONTEXT.format(context=context)
