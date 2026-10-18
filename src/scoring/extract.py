"""Pull the final Lean theorem statement out of a model output.

ReForm-8B writes `<think> ... <round> ... </round> ... </think>` and then its answer with a
```lean4 block (format from its repo, lean_plugins/reward.py). Qwen3-8B may also think first.
We read only the text after the last `</think>`, take the last closed ```lean/```lean4 block
that contains a theorem or lemma, and return its last declaration. Anything else is a format
failure.
"""
import re

FENCE = re.compile(r"```[ \t]*(?:lean4|lean)?[ \t]*\n(.*?)```", re.DOTALL)
DECL = re.compile(r"^[ \t]*(?:@\[[^\]]*\][ \t]*)?(?:private[ \t]+|protected[ \t]+)?(theorem|lemma)\b", re.MULTILINE)


def extract_statement(text):
    """Return (statement, None) or (None, reason)."""
    answer = text.rsplit("</think>", 1)[-1]
    blocks = [b for b in FENCE.findall(answer) if DECL.search(b)]
    if not blocks:
        return None, "no closed Lean code block with a theorem"
    block = blocks[-1]
    start = list(DECL.finditer(block))[-1].start()
    return block[start:].strip(), None
