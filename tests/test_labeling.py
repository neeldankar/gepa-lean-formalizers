import copy
import re

from src.config import load_config
from src.scoring.labeling import build_page

CFG = copy.deepcopy(load_config())


class Client:
    def __init__(self, replies=None):
        self.prompts, self.replies = [], list(replies or [])

    def chat(self, model, messages, **kw):
        self.prompts.append(messages[0]["content"])
        return self.replies.pop(0) if self.replies else "It says something."


def records():
    return [{"label_id": "x-01", "english": "a < b", "reference": "theorem candidate : 1 < 2 := by\n  sorry",
             "candidate": "theorem candidate : (1 : ℤ) < 2 := by\n  sorry"}]


def test_page_has_buttons_export_and_escapes(tmp_path):
    out = tmp_path / "p.html"
    build_page(Client(), CFG, records(), out, "k")
    html = out.read_text()
    assert html.count('data-label="faithful"') == 1 and 'data-label="unsure"' in html and "labels.csv" in html
    assert "a &lt; b" in html and "<p class=\"english\">a < b" not in html


def test_each_gloss_sees_one_statement_and_no_verdict_request(tmp_path):
    client = Client()
    build_page(client, CFG, records(), tmp_path / "p.html", "k")
    assert len(client.prompts) == 2
    assert "(1 : ℤ)" not in client.prompts[0] and "(1 : ℤ)" in client.prompts[1]
    assert all("a < b" not in p for p in client.prompts)  # glosses never see the English


def test_empty_gloss_is_retried_then_marked(tmp_path):
    client = Client(["", "", "", "fine"])
    full = build_page(client, CFG, records(), tmp_path / "p.html", "k")
    assert full[0]["reference_gloss"] == "(no gloss: the model returned nothing)" and full[0]["candidate_gloss"] == "fine"


def test_page_shows_only_the_given_fields(tmp_path):
    rec = {**records()[0], "arm": "B", "model": "Qwen3-8B"}  # extra fields must never reach the page
    out = tmp_path / "p.html"
    build_page(Client(), CFG, [rec], out, "k")
    html = out.read_text().lower()
    assert "qwen" not in html and "arm" not in re.findall(r"\w+", html)
