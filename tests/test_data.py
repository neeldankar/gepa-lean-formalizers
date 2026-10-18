import pytest

from src.data import minif2f, proofnet
from src.data.proofnet import read_jsonl


def test_proofnet_to_item_maps_fields():
    row = {
        "index": 7, "name": "Axler_exercise_1_2", "textbook": "Axler", "header": "import Mathlib",
        "helper": "", "informal_stmt": "Show x.", "formal_stmt": "theorem T : True := by\n  sorry",
        "informal_proof": "p", "formal_proof": "q",
    }
    item = proofnet.to_item(row)
    assert item["id"] == "pnv_007"
    assert "informal_proof" not in item and "formal_proof" not in item
    assert item["textbook"] == "Axler" and item["informal_stmt"] == "Show x."


def test_reference_content_skips_empty_helper():
    item = {"header": "import Mathlib\nopen Real", "helper": "", "formal_stmt": "theorem T : True := by\n  sorry"}
    assert proofnet.reference_content(item) == "import Mathlib\nopen Real\n\ntheorem T : True := by\n  sorry"
    item["helper"] = "def f := 1"
    assert proofnet.reference_content(item).count("\n\n") == 2


def test_proofnet_file():
    items = read_jsonl(proofnet.ITEMS_PATH)
    assert len(items) == 367
    assert len({it["id"] for it in items}) == 367
    assert all(it["formal_stmt"].rstrip().endswith("sorry") for it in items)


def test_strip_docstring():
    assert minif2f.strip_docstring("/-- Show that $x=1$.-/\n") == "Show that $x=1$."
    with pytest.raises(ValueError):
        minif2f.strip_docstring("-- not a docstring")


def test_minif2f_to_item():
    prefix = "/-- What is $1+1$? Show that it is 2.-/\n"
    row = {
        "name": "mathd_algebra_1",
        "informal_prefix": prefix,
        "formal_statement": "import Mathlib\nimport Aesop\n\nopen Real\n\n" + prefix + "theorem mathd_algebra_1 : 1 + 1 = 2 := by\n",
    }
    item = minif2f.to_item(row)
    assert item["header"] == "import Mathlib\nimport Aesop\n\nopen Real"
    assert item["informal_stmt"] == "What is $1+1$? Show that it is 2."
    assert item["formal_stmt"] == "theorem mathd_algebra_1 : 1 + 1 = 2 := by\n  sorry"
    assert "/--" not in proofnet.reference_content(item)


def test_minif2f_raw_file():
    rows = read_jsonl(minif2f.RAW_PATH)
    assert len(rows) == 244
    items = [minif2f.to_item(r) for r in rows]
    assert len({it["id"] for it in items}) == 244
