"""Mock formalizer, judge, reflection model and AXLE, for tests and the chunk 3 dry run only.

They plug in underneath the real LLMClient (`post=`) and AxleChecker (`client_factory=`), so caching,
cost logging, budget stops and scoring all run for real. The mock formalizer copies the reference
statement only if its instructions mention hypotheses; otherwise it drops the first hypothesis.
The mock reflection model always adds that rule, so a GEPA run on mocks should improve.
"""
import re
from types import SimpleNamespace

from src.config import ROOT
from src.data.proofnet import read_jsonl
from src.scoring.normalize import normalize_statement

RULE = "Keep every hypothesis from the problem."


def _items_by_english():
    items = read_jsonl(ROOT / "data/proofnet_verified.jsonl") + read_jsonl(ROOT / "data/minif2f.jsonl")
    return {it["informal_stmt"]: it for it in items}


def _drop_first_hypothesis(stmt):
    return re.sub(r"\s\((h\w*) : [^()]*\)", "", stmt, count=1)


class MockPosts:
    """`post` functions for each role; counts calls so tests can check the cache."""

    def __init__(self):
        self.items = _items_by_english()
        self.calls = {"formalizer": 0, "judge": 0, "reflection": 0}

    def _reply(self, text, prompt_tokens=100, completion_tokens=50):
        return {"choices": [{"message": {"content": text}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens}}

    def _item_in(self, text):
        # longest match first, so a short statement contained in a longer one can't win
        for english in sorted(self.items, key=len, reverse=True):
            if english and english in text:
                return self.items[english]
        raise KeyError("no known English statement in the prompt")

    def formalizer(self, body):
        self.calls["formalizer"] += 1
        prompt = body["messages"][0]["content"]
        # The item's English sits after the last code fence (the few-shot examples) and before the
        # last context block (each example has its own), so an example's English is never taken for the item.
        item = self._item_in(prompt.rsplit("\nLean 4 context", 1)[0].rsplit("```", 1)[-1])
        stmt = item["formal_stmt"]
        if "hypothes" not in prompt.split(item["informal_stmt"])[0].lower():
            stmt = _drop_first_hypothesis(stmt)
        return self._reply(f"<think>working</think>\n```lean4\n{stmt}\n```")

    def judge(self, body):
        self.calls["judge"] += 1
        prompt = body["messages"][0]["content"]
        item = self._item_in(prompt)
        candidate = prompt.split("```lean4\n")[-1].split("\n```")[0]
        same = candidate.split() == normalize_statement(item["formal_stmt"]).split()
        verdict = "faithful" if same else "unfaithful"
        tag = "null" if same else '"Missing premise"'
        return self._reply(f'{{"verdict": "{verdict}", "reason": "mock judge: {verdict}", "error_tag": {tag}}}')

    def reflection(self, body):
        self.calls["reflection"] += 1
        prompt = body["messages"][0]["content"]
        current = prompt.split("```")[1].strip() if "```" in prompt else ""
        new = current if RULE in current else f"{current}\n{RULE}".strip()
        return self._reply(f"```\n{new}\n```")


class MockAxleClient:
    """Every Lean file compiles; certificate attempts all succeed (so none survive the removal check)."""

    calls = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        pass

    async def check(self, **kwargs):
        MockAxleClient.calls += 1
        return SimpleNamespace(okay=True, lean_messages=SimpleNamespace(errors=[]), failed_declarations=[])

    async def normalize(self, content, **kwargs):
        MockAxleClient.calls += 1
        return SimpleNamespace(lean_messages=SimpleNamespace(errors=[]), content=content)
