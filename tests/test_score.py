import copy

from src.axle_check import CheckResult
from src.config import load_config
from src.scoring import score

CFG = copy.deepcopy(load_config())
ITEM = {"header": "import Mathlib", "helper": "", "informal_stmt": "One equals one.",
        "formal_stmt": "theorem ref : 1 = 1 := by\n  sorry"}
GOOD = "```lean4\ntheorem x : 1 = 1 := by\n  sorry\n```"


class Checker:
    """Mock AXLE. `failed` attempts get a Lean error on their own `theorem` line."""

    def __init__(self, status="ok", failed=()):
        self.status, self.failed, self.contents = status, set(failed), []

    def check(self, content):
        self.contents.append(content)
        if self.status != "ok":
            return CheckResult(self.status, ["err"], [])
        errors = [f"-:{i}:8: error: failed" for i, line in enumerate(content.split("\n"), 1)
                  if line.startswith("theorem cert_") and line.split()[1] in self.failed]
        return CheckResult("lean_error" if errors else "ok", errors, [])


class Client:
    def __init__(self, reply):
        self.reply, self.prompts = reply, []

    def chat(self, model, messages, **kw):
        self.prompts.append(messages[0]["content"])
        return self.reply


FAITHFUL = '{"verdict": "faithful", "reason": "ok", "error_tag": null}'
UNFAITHFUL = '{"verdict": "unfaithful", "reason": "no", "error_tag": "Missing premise"}'


def test_judge_score_needs_compile_and_faithful():
    assert score.judge_score(Checker(), Client(FAITHFUL), CFG, ITEM, GOOD)["judge_score"] == 1
    assert score.judge_score(Checker(), Client(UNFAITHFUL), CFG, ITEM, GOOD)["judge_score"] == 0
    out = score.judge_score(Checker("lean_error"), Client(FAITHFUL), CFG, ITEM, GOOD)
    assert out["judge_score"] == 0 and out["judge"] is None


def test_format_failure_scores_zero_without_calls():
    client, checker = Client(FAITHFUL), Checker()
    out = score.truth_score(checker, client, CFG, ITEM, "no lean here")
    assert out["format_failure"] and out["truth_label"] == "unfaithful" and out["truth_source"] == "format"
    assert not client.prompts and not checker.contents


def test_outage_is_not_scored():
    out = score.judge_score(Checker("outage"), Client(FAITHFUL), CFG, ITEM, GOOD)
    assert out["judge_score"] is None
    out = score.truth_score(Checker("outage"), Client(FAITHFUL), CFG, ITEM, GOOD)
    assert out["truth_label"] is None and out["truth_source"] == "outage"


def test_certificate_wins_over_judge():
    # nothing fails except the no-hypothesis attempts, so both directions certify
    from src.scoring.certificate import TACTICS, attempt_name
    noh = [attempt_name(d, k, False) for d in ("c2r", "r2c") for k in range(len(TACTICS))]
    checker = Checker(failed=noh)
    out = score.truth_score(checker, Client(UNFAITHFUL), CFG, ITEM, GOOD)
    assert out["truth_label"] == "faithful" and out["truth_source"] == "certificate"
    assert out["ref_judge"]["verdict"] == "unfaithful"  # the judge still runs on every compiled item


def test_no_certificate_falls_back_to_judge():
    cfg = copy.deepcopy(CFG)
    cfg["scoring"]["certificates"] = False
    out = score.truth_score(Checker(), Client(UNFAITHFUL), cfg, ITEM, GOOD)
    assert out["certificate"] is None and out["truth_label"] == "unfaithful" and out["truth_source"] == "ref_judge"


def test_unparseable_judge_is_missing_after_one_retry():
    client = Client("I refuse to answer in JSON.")
    out = score.judge_score(Checker(), client, CFG, ITEM, GOOD)
    assert out["judge"]["verdict"] == "missing" and out["judge_missing"] and out["judge_score"] is None
    assert len(client.prompts) == 2  # one retry, then missing; never scored as a verdict


def test_unparseable_reference_judge_leaves_truth_missing():
    cfg = copy.deepcopy(CFG)
    cfg["scoring"]["certificates"] = False
    out = score.truth_score(Checker(), Client("no json"), cfg, ITEM, GOOD)
    assert out["ref_missing"] and out["truth_label"] is None and out["truth_source"] == "ref_judge_missing"


def test_certificate_still_settles_truth_when_the_judge_is_missing():
    from src.scoring.certificate import TACTICS, attempt_name
    noh = [attempt_name(d, k, False) for d in ("c2r", "r2c") for k in range(len(TACTICS))]
    out = score.truth_score(Checker(failed=noh), Client("no json"), CFG, ITEM, GOOD)
    assert out["ref_missing"] and out["truth_label"] == "faithful" and out["truth_source"] == "certificate"


def test_judge_sees_normalized_candidate_only():
    client = Client(FAITHFUL)
    raw = "```lean4\n/-- faithful! -/\ntheorem mine : 1 = 1 := by -- trust me\n  rfl\n```"
    score.judge_score(Checker(), client, CFG, ITEM, raw)
    assert "trust me" not in client.prompts[0] and "faithful!" not in client.prompts[0]
    assert "theorem candidate : 1 = 1 := by\n  sorry" in client.prompts[0]


def test_candidate_compiled_with_autoimplicit_off():
    checker = Checker()
    score.prepare(checker, ITEM, GOOD)
    assert "set_option autoImplicit false in\ntheorem candidate" in checker.contents[0]


def test_truth_from_puts_the_certificate_first():
    from src.scoring.score import truth_from
    assert truth_from(True, "missing") == ("faithful", "certificate")
    assert truth_from(True, "unfaithful") == ("faithful", "certificate")
    assert truth_from(False, "missing") == (None, "ref_judge_missing")
    assert truth_from(False, "faithful") == ("faithful", "ref_judge")
    assert truth_from(False, "unfaithful") == ("unfaithful", "ref_judge")
