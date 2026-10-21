import copy
import json
import re

from src.config import load_config
from src.scoring.labeling import FIELDS, build_page, render_page

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


def full_records(n=3):
    return [{"label_id": f"P{k:02d}", "english": f"Show $x^{k}$ < y", "reference": "theorem candidate (x : ℝ) : x < 2 := by\n  sorry",
             "candidate": "theorem candidate (h : 0 < x) : x ≤ 2 := by\n  sorry", "reference_gloss": "ref gloss",
             "candidate_gloss": "cand gloss", "arm": "B", "config": "qwen_a3", "ref_verdict": "faithful",
             "judge_verdict": "unfaithful", "item_id": "pnv_001"} for k in range(1, n + 1)]


def embedded(page):
    return json.loads(page.split('<script id="data" type="application/json">')[1].split("</script>")[0])


def test_page_embeds_only_the_six_display_fields():
    page = render_page(full_records(), "chunk4-pilot")
    data = embedded(page)
    assert len(data) == 3 and all(set(r) == set(FIELDS) for r in data)
    low = page.lower()
    for word in ("qwen", "pnv_001", "verdict", "judge", "certif", "reform"):
        assert word not in low, word
    assert "arm" not in re.findall(r"\w+", low) and "config" not in re.findall(r"\w+", low)


def test_export_format_and_storage_keys_unchanged():
    page = render_page(full_records(), "chunk4-pilot")
    assert 'const KEY = "labels:" ' not in page and '"labels:chunk4-pilot"' in page  # same key as the first page
    assert '["label_id,label", ...ITEMS.map(r => r.label_id + "," + (labels[r.label_id] || ""))]' in page
    assert 'download("labels.csv"' in page and 'download("notes.csv"' in page and '"notes:chunk4-pilot"' in page


def test_shortcuts_list_help_progress_and_done_screen():
    page = render_page(full_records(20), "k")
    for key in ('k === "f"', 'k === "u"', 'k === "s"', '"arrowleft"', '"arrowright"', 'k === "n"', 'k === "?"', 'k === "l"'):
        assert key in page, key
    for shown in ("<kbd>F</kbd>", "<kbd>U</kbd>", "<kbd>S</kbd>", "<kbd>N</kbd>", "<kbd>?</kbd>", "&larr;", "&rarr;"):
        assert shown in page, shown
    assert page.count('class="jump"') == 20 and "0 of 20" in page and 'id="done"' in page and "All 20 items labeled." in page
    for notation in ("Finset.card", "ZMOD", "Filter.Tendsto", "atTop", "𝓝", "Function.Injective", "Polynomial", "↑n", "(h : 0 &lt; x)"):
        assert notation in page, notation
    assert "katex" in page.lower()


def test_page_never_compares_the_two_statements():
    page = render_page(full_records(), "k")
    script = page.split("<script>")[-1]
    # each statement is coloured on its own; no code reads both to diff or highlight differences
    assert "lean(r.reference)" in script and "lean(r.candidate)" in script
    assert "diff" not in script.lower() and not re.search(r"r\.reference[^;\n]*r\.candidate|r\.candidate[^;\n]*r\.reference", script)


def test_script_json_cannot_close_the_script_tag():
    recs = full_records(1)
    recs[0]["english"] = "</script><b>x</b> & y"
    data = embedded(render_page(recs, "k"))
    assert data[0]["english"] == "</script><b>x</b> & y"
