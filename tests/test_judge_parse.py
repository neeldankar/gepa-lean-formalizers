from src.scoring.judge import ERROR_TAGS, parse_json_reply


def test_parse_takes_last_valid_object():
    text = 'Thinking {"verdict": "maybe"} ... final: {"verdict": "Faithful", "reason": "same"}'
    assert parse_json_reply(text, False) == {"verdict": "faithful", "reason": "same"}


def test_reference_judge_needs_valid_tag_when_unfaithful():
    assert parse_json_reply('{"verdict": "unfaithful", "reason": "r", "error_tag": "Bad tag"}', True) is None
    out = parse_json_reply(f'{{"verdict": "unfaithful", "reason": "r", "error_tag": "{ERROR_TAGS[1]}"}}', True)
    assert out["error_tag"] == "Missing premise"
    assert parse_json_reply('{"verdict": "faithful", "reason": "r", "error_tag": "Missing premise"}', True)["error_tag"] is None


def test_garbage_is_none():
    assert parse_json_reply("no json here", False) is None
