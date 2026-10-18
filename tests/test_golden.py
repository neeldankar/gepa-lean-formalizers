"""Golden cases, live (AXLE and judges are cached on disk, so reruns cost nothing)."""
import os

import pytest

from src.axle_check import AxleChecker
from src.config import load_config, load_env
from src.data.proofnet import read_jsonl
from src.llm import LLMClient
from src.scoring.golden import CASES_PATH, run_golden, train_items

load_env()
CFG = load_config()


def test_golden_cases_use_train_items_only():
    train = train_items()
    assert all(c["item_id"] in train for c in read_jsonl(CASES_PATH))


@pytest.mark.live
@pytest.mark.skipif(not (os.environ.get("AXLE_API_KEY") and os.environ.get("TOGETHER_API_KEY")), reason="no API keys")
def test_golden_cases_pass():
    results = run_golden(AxleChecker(CFG["axle"]), LLMClient(CFG, chunk=2), CFG)
    failed = {r["case"]: {k: c for k, c in r["checks"].items() if not c["ok"]} for r in results if not r["passed"]}
    assert not failed
