from src.scoring.compile import candidate_content
from src.scoring.extract import extract_statement
from src.scoring.normalize import normalize_statement, signature_end


def block(s, tag="lean4"):
    return f"```{tag}\n{s}\n```"


def test_takes_last_block_with_theorem():
    text = block("theorem a : True := trivial") + "\nthen\n" + block("theorem b : False := by\n  sorry") + "\n" + block("#check Nat", "lean")
    assert extract_statement(text) == ("theorem b : False := by\n  sorry", None)


def test_ignores_blocks_inside_think():
    text = "<think>" + block("theorem inside : True := trivial") + "</think>\nAnswer:\n" + block("theorem outside : True := trivial")
    assert extract_statement(text)[0] == "theorem outside : True := trivial"


def test_think_without_answer_block_is_format_failure():
    text = "<think>" + block("theorem inside : True := trivial") + "</think>\nI give up."
    assert extract_statement(text)[0] is None


def test_last_declaration_in_block_and_lemma():
    text = block("def f := 1\n\nlemma helper : True := trivial\n\nlemma main (n : ℕ) : n = n := by\n  rfl")
    assert extract_statement(text)[0] == "lemma main (n : ℕ) : n = n := by\n  rfl"


def test_plain_fence_and_unclosed_fence():
    assert extract_statement("```\ntheorem t : True := trivial\n```")[0] == "theorem t : True := trivial"
    assert extract_statement("```lean4\ntheorem t : True := by\n  sor")[0] is None


def test_no_code_is_format_failure():
    stmt, reason = extract_statement("theorem t : True := trivial")
    assert stmt is None and reason


def test_normalize_renames_strips_and_sorries():
    out = normalize_statement("/-- doc -/\nlemma Foo.bar_1 (n : ℕ) -- faithful\n  : n = n := by\n  rfl")
    assert out == "theorem candidate (n : ℕ) \n  : n = n := by\n  sorry"


def test_normalize_keeps_colon_eq_inside_brackets():
    stmt = "theorem t (f : ℕ → ℕ) (hf : f = fun x => (let y := x; y)) : f 0 = 0 := by simp [hf]"
    out = normalize_statement(stmt)
    assert out.endswith(": f 0 = 0 := by\n  sorry") and "let y := x" in out


def test_normalize_rejects_non_theorems():
    assert normalize_statement("def f : ℕ := 1") is None
    assert normalize_statement("theorem t : True") is None


def test_signature_end():
    assert signature_end("theorem t {a : ℕ} : a = a := rfl") == len("theorem t {a : ℕ} : a = a ")


def test_candidate_content_turns_autoimplicit_off_for_the_theorem_only():
    item = {"header": "import Mathlib\nopen Real", "helper": "def g := 1"}
    content = candidate_content(item, "theorem candidate : g = 1 := by\n  sorry")
    assert content == "import Mathlib\nopen Real\n\ndef g := 1\n\nset_option autoImplicit false in\ntheorem candidate : g = 1 := by\n  sorry"
