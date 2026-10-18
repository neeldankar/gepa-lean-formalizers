import copy

import pytest

from src.config import load_config
from src.costs import GpuMeter, summarize
from src.generate import generate
from src.llm import BudgetExceeded
from src.prompting import load_fewshot, load_instructions, user_message

CFG = copy.deepcopy(load_config())
ITEM = {"informal_stmt": "Show that 1 = 1.", "header": "import Mathlib\nopen Real", "helper": "def g := 1"}
REFORM = "Think step by step to translate the mathematical problem in natural language to Lean 4, and verify the consistency."


def test_arm_c_message_starts_with_reforms_exact_prompt():
    instructions = load_instructions("prompts/arm_C.txt")
    assert instructions == REFORM
    msg = user_message(instructions, ITEM)
    assert msg.startswith(f"{REFORM}\n{ITEM['informal_stmt']}\n")  # ReForm's PROMPT, then our context block
    assert msg.endswith("```lean4\nimport Mathlib\nopen Real\n\ndef g := 1\n```\n")


def test_context_block_is_identical_across_arms():
    a = user_message(load_instructions("prompts/arm_A.txt"), ITEM)
    c = user_message(load_instructions("prompts/arm_C.txt"), ITEM)
    assert a.split(ITEM["informal_stmt"], 1)[1] == c.split(ITEM["informal_stmt"], 1)[1]


class Recorder:
    def __init__(self):
        self.calls = []

    def chat_full(self, model, messages, **kw):
        self.calls.append({"model": model, "messages": messages, **kw})
        return {"text": "", "usage": {}, "finish_reason": "stop"}


def test_sampling_settings_identical_across_models_and_thinking_flag():
    rec = Recorder()
    generate(rec, CFG, "qwen3-8b", "x", ITEM, sample=2)
    generate(rec, CFG, "reform-8b", "x", ITEM, sample=2)
    q, r = rec.calls
    for k in ("temperature", "max_tokens", "seed", "sample"):
        assert q[k] == r[k]
    assert q["extra"] == {"chat_template_kwargs": {"enable_thinking": CFG["models"]["qwen3-8b"]["enable_thinking"]}}
    assert r["extra"] == {} and q["model"] == "qwen3-8b" and r["model"] == "reform-8b"


def test_gpu_meter_logs_hours_and_stops_at_cap(tmp_path):
    cfg = copy.deepcopy(CFG)
    cfg["budget"]["chunk_caps_usd"][4] = 1.0
    cfg["gpu"]["usd_per_hour"] = 2.7  # fixed here so the test does not follow the pod rate
    t = [0.0]
    meter = GpuMeter(cfg, 4, "r1", costs_path=tmp_path / "c.jsonl", clock=lambda: t[0])
    t[0] = 600.0  # 10 minutes
    meter.tick()
    t[0] = 3600.0  # 50 more minutes: total $2.70 > $1 cap
    with pytest.raises(BudgetExceeded):
        meter.tick()
    import json
    rows = [json.loads(line) for line in (tmp_path / "c.jsonl").read_text().splitlines()]
    assert rows[0]["usd"] == pytest.approx(2.7 / 6) and summarize(rows)["by_run"]["r1"]["calls"] == 2


def test_no_fewshot_message_is_byte_identical():
    # Arm C (and D) carry no few-shot block: the message is exactly what it was before the block existed.
    c = load_instructions("prompts/arm_C.txt")
    expected = f"{c}\n{ITEM['informal_stmt']}\n" + "\nLean 4 context (use these imports, opens and definitions; write one theorem):\n```lean4\nimport Mathlib\nopen Real\n\ndef g := 1\n```\n"
    assert user_message(c, ITEM) == expected and user_message(c, ITEM, "") == expected


def test_fewshot_sits_between_instructions_and_the_problem():
    a, shots = load_instructions("prompts/arm_A.txt"), load_fewshot("prompts/fewshot.txt")
    msg = user_message(a, ITEM, shots)
    assert msg.startswith(f"{a}\n\n{shots}\n{ITEM['informal_stmt']}\n")
    assert msg.split(ITEM["informal_stmt"], 1)[1] == user_message(a, ITEM).split(ITEM["informal_stmt"], 1)[1]
