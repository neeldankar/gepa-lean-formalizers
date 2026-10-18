import json

from src.axle_check import AxleChecker
from src.config import load_config
from src.scoring import memorization
from src.scoring.golden import train_items

CFG = load_config()


def test_theorem_part():
    assert memorization.theorem_part("import Mathlib\nopen Real\n\ntheorem t : True := trivial") == "theorem t : True := trivial"
    assert memorization.theorem_part("instance i : Foo := sorry") is None


def test_original_proofnet_is_skipped_as_lean3():
    assert memorization.SKIPPED == {"ProofNet (original)": "Lean 3 only"}


def test_references_match_themselves_and_renames_spacing_comments_dont_matter():
    index = memorization.load_index()
    items = list(train_items().values())[:5]
    checker = AxleChecker(CFG["axle"])
    same = [it["formal_stmt"] for it in items]
    variants = [s.replace("theorem ", "theorem   renamed_", 1).replace(" :", "  : -- c\n", 1) for s in same]
    assert all("ProofNet-Verified" in m for m in memorization.exact_matches(checker, index, items, same))
    assert all("ProofNet-Verified" in m for m in memorization.exact_matches(checker, index, items, variants))


def test_changed_statement_does_not_match():
    index = memorization.load_index()
    item = train_items()["pnv_075"]
    changed = item["formal_stmt"].replace("a > 1", "a > 2")
    assert memorization.exact_matches(AxleChecker(CFG["axle"]), index, [item], [changed]) == [[]]


def test_index_file_counts():
    data = json.loads(memorization.INDEX_PATH.read_text())
    assert data["counts"]["ProofNet-Verified"] == {"rows": 367, "keys": 367}
