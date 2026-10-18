import pytest

from src.config import load_config
from src.scoring.strip import CASES, squash, strip_comments


@pytest.mark.parametrize("name,inp,expected", CASES, ids=[c[0] for c in CASES])
def test_our_stripper(name, inp, expected):
    assert squash(strip_comments(inp)) == squash(expected)


def test_config_uses_contest_winner():
    from axle import remove_comments
    axle_passes_all = all(squash(remove_comments(i)) == squash(e) for _, i, e in CASES)
    assert load_config()["scoring"]["stripper"] == ("axle" if axle_passes_all else "ours")


def test_block_comment_does_not_glue_tokens():
    assert squash(strip_comments("a/- x -/b")) == "a b"
