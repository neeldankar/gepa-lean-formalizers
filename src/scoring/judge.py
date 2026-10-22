"""LLM judges. Both return JSON; one re-ask on unparseable output, then the verdict is missing
(`verdict: "missing"`, `missing: True`). A missing verdict is never scored as faithful or unfaithful
(Neel, chunk 4 freeze); results count it per arm.

The optimization judge sees only the English and the candidate. The reference judge also sees the
reference and tags unfaithful items with one error type from ProofNet-Verified's taxonomy.
"""
import json
import re

from src.config import ROOT

ERROR_TAGS = [
    "Misunderstanding of informal statement",
    "Missing premise",
    "Misunderstanding of Mathlib",
    "Missing implicit premise",
    "Misunderstanding of Lean",
    "Adding extra case",
    "Adding extra conclusion",
]
VERDICTS = ("faithful", "unfaithful")
MISSING = "missing"
OLD_MISSING = "unparseable"  # what pilot rows (before the freeze) recorded for the same case


def is_missing(verdict):
    return verdict in (MISSING, OLD_MISSING)


def load_prompt(name):
    return (ROOT / "prompts" / f"{name}.txt").read_text()


def parse_json_reply(text, need_tag):
    """Last {...} object in the reply with a valid verdict (and tag, for the reference judge)."""
    for raw in reversed(re.findall(r"\{.*?\}", text, re.DOTALL)):
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            continue
        verdict = str(obj.get("verdict", "")).strip().lower()
        if verdict not in VERDICTS:
            continue
        out = {"verdict": verdict, "reason": str(obj.get("reason", ""))}
        if need_tag:
            tag = obj.get("error_tag")
            if verdict == "faithful":
                tag = None
            elif tag not in ERROR_TAGS:
                continue
            out["error_tag"] = tag
        return out
    return None


def run_judge(client, model, prompt, purpose, need_tag, max_tokens):
    messages = [{"role": "user", "content": prompt}]
    for attempt in range(2):
        reply = client.chat(model, messages, purpose=purpose, max_tokens=max_tokens, sample=attempt)
        parsed = parse_json_reply(reply, need_tag)
        if parsed:
            return parsed
    return {"verdict": MISSING, "missing": True, "reason": reply[-500:], **({"error_tag": None} if need_tag else {})}


def optimization_judge(client, cfg, english, candidate):
    prompt = load_prompt("judge_opt").format(english=english, candidate=candidate)
    return run_judge(client, cfg["judges"]["optimization"], prompt, "opt_judge", False, cfg["judges"]["max_tokens"])


def reference_judge(client, cfg, english, reference, candidate):
    prompt = load_prompt("judge_ref").format(english=english, reference=reference, candidate=candidate,
                                             tags="\n".join(f"- {t}" for t in ERROR_TAGS))
    return run_judge(client, cfg["judges"]["reference"], prompt, "ref_judge", True, cfg["judges"]["max_tokens"])
