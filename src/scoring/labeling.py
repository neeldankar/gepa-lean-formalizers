"""Blind labeling page: one local HTML file, labels exported from the browser as labels.csv.

Each record shows the English, the reference and the candidate. Every Lean statement gets its own
plain-English gloss from a cheap model that sees only that one statement. Arm and model are never
on the page; callers pass opaque `label_id`s and keep the mapping in a separate file.
"""
import html

from src.scoring.judge import load_prompt


def gloss(client, cfg, statement):
    """The gloss model may spend its whole budget thinking; one retry, then a visible placeholder."""
    messages = [{"role": "user", "content": load_prompt("gloss").format(statement=statement)}]
    for sample in range(2):
        text = client.chat(cfg["judges"]["gloss"], messages, purpose="gloss",
                           max_tokens=cfg["judges"]["gloss_max_tokens"], sample=sample).strip()
        if text:
            return text
    return "(no gloss: the model returned nothing)"


def card(rec):
    e = html.escape
    return f"""
<section class="card" data-id="{e(rec['label_id'])}">
  <h2>{e(rec['label_id'])}</h2>
  <h3>English</h3><p class="english">{e(rec['english'])}</p>
  <div class="pair">
    <div><h3>Reference</h3><pre>{e(rec['reference'])}</pre><p class="gloss">{e(rec['reference_gloss'])}</p></div>
    <div><h3>Candidate</h3><pre>{e(rec['candidate'])}</pre><p class="gloss">{e(rec['candidate_gloss'])}</p></div>
  </div>
  <div class="buttons">
    <button data-label="faithful">Faithful</button>
    <button data-label="unfaithful">Unfaithful</button>
    <button data-label="unsure">Unsure</button>
  </div>
</section>"""


PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Faithfulness labels</title>
<style>
:root {{ --bg:#fff; --fg:#1d1d1f; --muted:#5f6368; --card:#f6f7f9; --line:#d9dce1; --accent:#2457c5; --chosen:#dfe8fb; }}
@media (prefers-color-scheme: dark) {{ :root {{ --bg:#16181c; --fg:#e8eaed; --muted:#9aa0a6; --card:#1f2228; --line:#353a42; --accent:#8ab4f8; --chosen:#253552; }} }}
body {{ background:var(--bg); color:var(--fg); font:16px/1.5 system-ui, sans-serif; margin:0 auto; max-width:1100px; padding:16px; }}
header {{ position:sticky; top:0; background:var(--bg); padding:8px 0; border-bottom:1px solid var(--line); display:flex; gap:12px; align-items:center; flex-wrap:wrap; }}
.card {{ background:var(--card); border:1px solid var(--line); border-radius:8px; padding:12px 16px; margin:16px 0; }}
.pair {{ display:grid; grid-template-columns:1fr 1fr; gap:16px; }}
@media (max-width:700px) {{ .pair {{ grid-template-columns:1fr; }} }}
pre {{ white-space:pre-wrap; overflow-wrap:anywhere; background:var(--bg); border:1px solid var(--line); border-radius:6px; padding:8px; font-size:14px; }}
.gloss {{ color:var(--muted); font-size:14px; }}
h2 {{ font-size:14px; color:var(--muted); margin:0; }} h3 {{ font-size:15px; margin:8px 0 4px; }}
button {{ font:inherit; padding:6px 14px; border:1px solid var(--line); border-radius:6px; background:var(--bg); color:var(--fg); cursor:pointer; }}
button.chosen {{ background:var(--chosen); border-color:var(--accent); }}
</style></head><body>
<header><strong>Faithfulness labels</strong><span id="progress"></span><button id="export">Export labels.csv</button></header>
{cards}
<script>
const KEY = "labels:{page_key}";
let labels = {{}};
try {{ labels = JSON.parse(localStorage.getItem(KEY) || "{{}}"); }} catch (e) {{}}
const cards = [...document.querySelectorAll(".card")];
function render() {{
  for (const c of cards) for (const b of c.querySelectorAll("button"))
    b.classList.toggle("chosen", labels[c.dataset.id] === b.dataset.label);
  document.getElementById("progress").textContent = Object.keys(labels).length + " / " + cards.length + " labeled";
}}
for (const c of cards) for (const b of c.querySelectorAll("button")) b.onclick = () => {{
  labels[c.dataset.id] = b.dataset.label;
  try {{ localStorage.setItem(KEY, JSON.stringify(labels)); }} catch (e) {{}}
  render();
}};
document.getElementById("export").onclick = () => {{
  const rows = ["label_id,label", ...cards.map(c => c.dataset.id + "," + (labels[c.dataset.id] || ""))];
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([rows.join("\\n") + "\\n"], {{type: "text/csv"}}));
  a.download = "labels.csv"; a.click();
}};
render();
</script></body></html>
"""


def build_page(client, cfg, records, out_path, page_key):
    """records: [{label_id, english, reference, candidate}] in display order."""
    full = []
    for rec in records:
        full.append({**rec, "reference_gloss": gloss(client, cfg, rec["reference"]),
                     "candidate_gloss": gloss(client, cfg, rec["candidate"])})
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(PAGE.format(cards="\n".join(card(r) for r in full), page_key=html.escape(page_key)))
    return full

