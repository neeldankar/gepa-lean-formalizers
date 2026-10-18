"""Build the formalizer's user message. GEPA only ever edits `instructions`.

Every arm: instructions, newline, English statement, newline (arm C's first part is exactly
ReForm-8B's released prompt, prereg Changes item 11), then one fixed block with the item's Lean
header and helper definitions. Arms A, B, E and F also carry a fixed few-shot block of train
examples right after the instructions; it is never part of what GEPA edits.
"""
from src.config import ROOT

CONTEXT = "\nLean 4 context (use these imports, opens and definitions; write one theorem):\n```lean4\n{context}\n```\n"


def load_instructions(path):
    return (ROOT / path).read_text().rstrip("\n")


def load_fewshot(path):
    """The fixed few-shot block ("" when an arm has none)."""
    return load_instructions(path) if path else ""


def context_block(item):
    """The fixed block with the item's Lean header and helper definitions."""
    return CONTEXT.format(context="\n\n".join(p for p in (item["header"], item["helper"]) if p.strip()))


def user_message(instructions, item, fewshot=""):
    head = f"{instructions}\n\n{fewshot}" if fewshot else instructions
    return f"{head}\n{item['informal_stmt']}\n" + context_block(item)
