"""GEPA runner on mocks: budget, feedback, firewall, cache, cost cap."""
import copy
import inspect
import json

import pytest

from src import gepa_adapter, runner
from src.axle_check import AxleChecker
from src.config import load_config
from src.data import firewall
from src.llm import LLMClient
from src.mocks import RULE, MockAxleClient, MockPosts

BASE = load_config()


def make_cfg(budget=150, cap=10):
    cfg = copy.deepcopy(BASE)
    cfg["gepa"]["max_metric_calls"] = budget
    cfg["gepa"]["runs"] = {"T_s0": {"model": "qwen3-8b", "seed": 0, "seed_prompt": "prompts/arm_A.txt"}}
    cfg["budget"]["chunk_caps_usd"][3] = cap
    cfg["axle"]["outage_backoff_seconds"] = 0
    return cfg


def run(tmp_path, cfg, posts, runs_sub="runs"):
    costs = tmp_path / "costs.jsonl"
    kw = dict(cache_dir=tmp_path / "llm_cache", costs_path=costs)
    gen = LLMClient(cfg, 3, post=posts.formalizer, base_url="http://mock", api_key_env=None, **kw)
    judge = LLMClient(cfg, 3, post=posts.judge, **kw)
    refl = LLMClient(cfg, 3, post=posts.reflection, **kw)
    checker = AxleChecker(cfg["axle"], client_factory=MockAxleClient, cache_dir=tmp_path / "axle_cache")
    return runner.run_gepa(cfg, "T_s0", gen, judge, refl, checker, runs_dir=tmp_path / runs_sub), costs


def test_run_stops_at_metric_call_budget_and_improves(tmp_path):
    cfg = make_cfg(budget=150)
    result, _ = run(tmp_path, cfg, MockPosts())
    assert result["status"] == "done"
    # GEPA checks its budget between iterations, so it can overshoot by at most one iteration:
    # a 3-item minibatch twice plus one full validation pass (70 items).
    assert 150 <= result["total_metric_calls"] <= 150 + 3 + 3 + 70
    saved = json.loads((tmp_path / "runs/T_s0/candidates.json").read_text())
    assert saved["val_aggregate_scores"][saved["best_idx"]] > saved["val_aggregate_scores"][0]
    assert RULE in (tmp_path / "runs/T_s0/best_prompt.txt").read_text()
    assert (tmp_path / "runs/T_s0/DONE").exists()


def test_second_identical_run_makes_zero_new_calls(tmp_path):
    cfg = make_cfg(budget=100)
    run(tmp_path, cfg, MockPosts(), runs_sub="runs1")
    MockAxleClient.calls = 0
    posts = MockPosts()
    result, _ = run(tmp_path, cfg, posts, runs_sub="runs2")
    assert result["status"] == "done"
    assert posts.calls == {"formalizer": 0, "judge": 0, "reflection": 0}
    assert MockAxleClient.calls == 0


def test_cost_cap_stops_a_run(tmp_path):
    cfg = make_cfg(budget=500, cap=0.0005)
    result, costs = run(tmp_path, cfg, MockPosts())
    assert result["status"] == "stopped" and "cap" in result["reason"]
    assert (tmp_path / "runs/T_s0/STOPPED").exists() and not (tmp_path / "runs/T_s0/DONE").exists()


def test_feedback_has_lean_errors_and_judge_reason():
    trace = {"score": 0, "format_failure": False, "format_reason": None, "compiled": False, "compile_status": "lean_error",
             "lean_errors": ["-:3:4: error: unknown identifier 'Nat.Prme'"], "judge": None}
    assert "unknown identifier 'Nat.Prme'" in gepa_adapter.feedback_text(trace)
    trace.update(compiled=True, lean_errors=[], judge={"verdict": "unfaithful", "reason": "uses ℕ, the text says integers"})
    text = gepa_adapter.feedback_text(trace)
    assert "unfaithful" in text and "uses ℕ, the text says integers" in text


def test_reflective_dataset_records(tmp_path):
    cfg = make_cfg()
    item = firewall.gepa_items("train")[0]
    adapter = gepa_adapter.FormalizerAdapter(cfg, "qwen3-8b", None, None, None)
    sample = {"extracted": "theorem x : True := trivial", "score": 1, "format_failure": False, "format_reason": None,
              "compiled": True, "compile_status": "ok", "lean_errors": [], "judge": {"verdict": "faithful", "reason": "same"}}
    batch = gepa_adapter.EvaluationBatch(outputs=[], scores=[1], trajectories=[{"item": item, "samples": [sample], "score": 1}])
    data = adapter.make_reflective_dataset({"instructions": "x"}, batch, ["instructions"])
    rec = data["instructions"][0]
    assert item["informal_stmt"] in rec["Inputs"] and rec["Generated Outputs"] == sample["extracted"]
    assert "Judge reason: same" in rec["Feedback"]


def test_firewall_gepa_loader_only_sees_train_and_val():
    assert len(firewall.gepa_items("train")) == 50 and len(firewall.gepa_items("val")) == 70
    for split in ("test", "minif2f", "all"):
        with pytest.raises(firewall.FirewallError):
            firewall.gepa_items(split)


def test_firewall_rejects_test_items_in_a_gepa_batch():
    splits = json.loads((firewall.ROOT / "data/splits.json").read_text())
    with pytest.raises(firewall.FirewallError):
        firewall.check_gepa_batch([{"id": splits["test"][0]}])
    with pytest.raises(firewall.FirewallError):
        firewall.check_gepa_batch([{"id": "minif2f_mathd_algebra_478"}])


def test_heldout_data_locked_until_every_gepa_run_is_done(tmp_path):
    cfg = make_cfg()
    with pytest.raises(firewall.FirewallError):
        firewall.heldout_items("test", cfg, runs_dir=tmp_path)
    (tmp_path / "T_s0").mkdir()
    (tmp_path / "T_s0/DONE").write_text("ok\n")
    assert len(firewall.heldout_items("test", cfg, runs_dir=tmp_path)) == 247


def test_gepa_code_never_references_heldout_loaders():
    for module in (runner, gepa_adapter):
        src = inspect.getsource(module)
        assert "heldout_items" not in src and "minif2f" not in src.lower()


def test_gepa_never_edits_the_fewshot_suffix(tmp_path):
    """The optimized component is the instruction text only; the few-shot block is a fixed suffix."""
    cfg = make_cfg(budget=150)
    cfg["gepa"]["runs"]["T_s0"]["fewshot"] = "prompts/fewshot.txt"
    shots = (runner.ROOT / "prompts/fewshot.txt").read_text().rstrip("\n")
    seed = runner.load_instructions("prompts/arm_A.txt")
    posts, sent = MockPosts(), []
    def formalizer(body):
        sent.append(body["messages"][0]["content"])
        return posts.formalizer(body)
    kw = dict(cache_dir=tmp_path / "llm_cache", costs_path=tmp_path / "costs.jsonl")
    gen = LLMClient(cfg, 3, post=formalizer, base_url="http://mock", api_key_env=None, **kw)
    judge = LLMClient(cfg, 3, post=posts.judge, **kw)
    refl = LLMClient(cfg, 3, post=posts.reflection, **kw)
    checker = AxleChecker(cfg["axle"], client_factory=MockAxleClient, cache_dir=tmp_path / "axle_cache")
    result = runner.run_gepa(cfg, "T_s0", gen, judge, refl, checker, runs_dir=tmp_path / "runs")
    assert result["status"] == "done" and posts.calls["reflection"] > 0
    out = tmp_path / "runs/T_s0"
    candidates = [c[gepa_adapter.COMPONENT] for c in json.loads((out / "candidates.json").read_text())["candidates"]]
    assert len(candidates) > 1 and candidates[0] == seed
    lines = [l for l in shots.splitlines() if l.strip() and not l.startswith("```")]
    assert not any(l in c for c in candidates for l in lines)          # no candidate carries any example line
    assert "Example 1:" not in (out / "best_prompt.txt").read_text()
    assert sent and all(f"\n\n{shots}\n" in m for m in sent)            # every formalizer call carries it verbatim
    assert all(any(m.startswith(f"{c}\n\n{shots}\n") for c in candidates) for m in sent)  # right after the instructions


def test_gepa_trainset_leaves_out_the_fewshot_examples():
    ids = [it["id"] for it in runner.gepa_trainset(BASE)]
    train = json.loads((runner.ROOT / "data/splits.json").read_text())["train"]
    assert len(ids) == 47 and set(ids) <= set(train)
    assert not set(ids) & set(BASE["fewshot"]["ids"]) and set(train) - set(ids) == set(BASE["fewshot"]["ids"])


@pytest.mark.parametrize("fewshot", [None, "prompts/fewshot.txt"])
def test_run_gepa_passes_the_47_item_trainset(tmp_path, monkeypatch, fewshot):
    # Every GEPA run (B with the few-shot block, D without) trains on the same 47 items; val is unchanged.
    seen = {}
    def fake_optimize(**kw):
        seen.update(kw)
        raise runner.BudgetExceeded("stop after capturing the arguments")
    monkeypatch.setattr(runner.gepa, "optimize", fake_optimize)
    cfg = make_cfg()
    if fewshot:
        cfg["gepa"]["runs"]["T_s0"]["fewshot"] = fewshot
    run(tmp_path, cfg, MockPosts())
    assert [it["id"] for it in seen["trainset"]] == [it["id"] for it in runner.gepa_trainset(cfg)]
    assert len(seen["trainset"]) == 47 and len(seen["valset"]) == 70


def test_failed_reflection_stops_the_run_without_done(tmp_path):
    """GEPA swallows reflection errors; our runner must not mark such a run DONE (chunk 4 pilot bug)."""
    cfg = make_cfg(budget=150)
    cfg["llm"]["retries"] = 0
    posts = MockPosts()
    def down(body):
        raise runner.ReflectionFailed("HTTP 400: endpoint_not_ready")  # what the client raises, here from the mock
    posts.reflection = down
    result, _ = run(tmp_path, cfg, posts)
    out = tmp_path / "runs/T_s0"
    assert result["status"] == "stopped" and "reflection" in result["reason"]
    assert (out / "STOPPED").exists() and not (out / "DONE").exists() and not (out / "best_prompt.txt").exists()
    assert result["metric_calls"] < 150  # it stops at the first evaluation after the failure, not at the budget


def test_cut_off_reflection_reply_stops_the_run(tmp_path):
    """A reflection reply that hits max_tokens (Kimi-K3 reasons first) must not become a candidate."""
    cfg = make_cfg(budget=150)
    posts = MockPosts()
    full = posts.reflection
    def cut_off(body):
        reply = full(body)
        reply["choices"][0]["finish_reason"] = "length"
        return reply
    posts.reflection = cut_off
    result, _ = run(tmp_path, cfg, posts)
    assert result["status"] == "stopped" and "cut off" in result["reason"]
    assert not (tmp_path / "runs/T_s0/DONE").exists()


def test_candidates_saved_without_any_truth_score(tmp_path, monkeypatch):
    """Item 2: every candidate's val outputs are saved, and GEPA's code path never reaches a truth score."""
    from src.scoring import certificate, judge, score
    def forbidden(*a, **k):
        raise AssertionError("GEPA code path reached a truth-score function")
    for mod, name in ((score, "truth_score"), (judge, "reference_judge"), (certificate, "certificate")):
        monkeypatch.setattr(mod, name, forbidden)
    for mod in (gepa_adapter, runner):  # nor is any truth function imported into GEPA's modules by name
        assert not {"truth_score", "reference_judge", "certificate", "truth_label"} & set(vars(mod))
    result, _ = run(tmp_path, make_cfg(budget=150), MockPosts())
    assert result["status"] == "done"
    out = tmp_path / "runs/T_s0"
    cands = json.loads((out / "candidates.json").read_text())["candidates"]
    files = sorted((out / "candidates").glob("*.jsonl"))
    assert len(files) == len(cands) > 1
    val_ids = {it["id"] for it in runner.gepa_items("val")}
    for f in files:
        lines = [json.loads(l) for l in f.read_text().splitlines()]
        assert lines[0]["instructions"] in [c[gepa_adapter.COMPONENT] for c in cands]
        rows = lines[1:]
        assert {r["item_id"] for r in rows} == val_ids and len(rows) == 70
        assert all(set(r) == {"item_id", "sample", "output", "extracted", "compile_status", "compiled", "lean_errors",
                              "judge_verdict", "judge_reason", "score"} for r in rows)


@pytest.mark.parametrize("role", ["judge", "formalizer"])
def test_a_hung_judge_or_formalizer_call_stops_the_run_and_says_so(tmp_path, role):
    """One hung API call must not stall a GEPA run: it is cut off, retried once, then the run stops with STOPPED."""
    import time
    cfg = make_cfg(budget=150)
    cfg["llm"].update(timeout_seconds=0.2, long_timeout_seconds=0.2, retries=1, long_retries=1, backoff_seconds=0)
    posts = MockPosts()
    real = getattr(posts, role)
    seen = []
    def hangs_once_seeded(body):
        seen.append(1)
        if len(seen) > 5:  # let a few calls through, then hang for good
            time.sleep(30)
        return real(body)
    setattr(posts, role, hangs_once_seeded)
    t0 = time.monotonic()
    result, _ = run(tmp_path, cfg, posts)
    out = tmp_path / "runs/T_s0"
    assert result["status"] == "stopped" and "gave up after 2 attempts" in result["reason"]
    assert "no reply within" in (out / "STOPPED").read_text() and not (out / "DONE").exists()
    assert time.monotonic() - t0 < 20


def test_adapter_scores_a_missing_judge_verdict_zero_without_stopping(tmp_path):
    import copy as _copy
    from src.axle_check import AxleChecker
    from src.data.firewall import gepa_items
    from src.llm import LLMClient
    from src.mocks import MockAxleClient, MockPosts
    cfg = _copy.deepcopy(load_config())
    posts = MockPosts()
    kw = dict(cache_dir=tmp_path / "llm", costs_path=tmp_path / "costs.jsonl")
    gen = LLMClient(cfg, 3, post=posts.formalizer, base_url="http://mock", api_key_env=None, **kw)
    judge = LLMClient(cfg, 3, post=lambda body: posts._reply("no JSON here"), **kw)
    checker = AxleChecker(cfg["axle"], client_factory=MockAxleClient, cache_dir=tmp_path / "axle")
    adapter = gepa_adapter.FormalizerAdapter(cfg, "qwen3-8b", gen, judge, checker)
    item = next(it for it in gepa_items("train") if it["id"] == "pnv_004")
    r = adapter.score_one("Translate.", item, 0)
    assert r["compiled"] and r["judge_missing"] and r["score"] == 0
    text = gepa_adapter.feedback_text({**r, "judge": r["judge"]})
    assert "could not be read" in text and "unfaithful" not in text
