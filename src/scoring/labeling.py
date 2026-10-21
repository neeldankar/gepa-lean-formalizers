"""Blind labeling page: one local HTML file, labels exported from the browser as labels.csv.

Each record shows the English, the reference and the candidate. Every Lean statement gets its own
plain-English gloss from a cheap model that sees only that one statement. Arm and model are never
on the page; callers pass opaque `label_id`s and keep the mapping in a separate file. Only the six
fields in FIELDS reach the page, and the page never compares the two statements.

The page (chunk 4 rebuild, Neel's spec): one item at a time, dark, KaTeX for the English, the two Lean
statements side by side with simple syntax colouring, big Faithful / Unfaithful / Unsure buttons, a
notes box, keyboard shortcuts, a progress bar, a list view, autosave to localStorage (labels under the
same key as the first page), labels.csv export (`label_id,label`, unchanged) plus a separate
notes.csv, a done screen, and a `?` panel with generic Lean notation.
"""
import html
import json

from src.scoring.judge import load_prompt

FIELDS = ("label_id", "english", "reference", "candidate", "reference_gloss", "candidate_gloss")


def gloss(client, cfg, statement):
    """The gloss model may spend its whole budget thinking; one retry, then a visible placeholder."""
    messages = [{"role": "user", "content": load_prompt("gloss").format(statement=statement)}]
    for sample in range(2):
        text = client.chat(cfg["judges"]["gloss"], messages, purpose="gloss",
                           max_tokens=cfg["judges"]["gloss_max_tokens"], sample=sample).strip()
        if text:
            return text
    return "(no gloss: the model returned nothing)"


def page_data(records):
    """The records as JSON for the page: whitelisted fields only, safe inside a <script> element."""
    data = [{k: r[k] for k in FIELDS} for r in records]
    return json.dumps(data, ensure_ascii=False).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


def list_items(records):
    """The list view, rendered here so it needs no script to show which items exist."""
    return "\n".join(
        f'<li><button class="jump" data-i="{i}"><span class="lid">{html.escape(r["label_id"])}</span>'
        f'<span class="snip">{html.escape(r["english"][:90])}</span><span class="state"></span></button></li>'
        for i, r in enumerate(records))


def render_page(records, page_key):
    """records: [{label_id, english, reference, candidate, reference_gloss, candidate_gloss}] in display order."""
    return (PAGE.replace("__DATA__", page_data(records)).replace("__KEY__", html.escape(page_key))
            .replace("__LIST__", list_items(records)).replace("__N__", str(len(records))))


def build_page(client, cfg, records, out_path, page_key):
    """records: [{label_id, english, reference, candidate}] in display order. Adds the glosses."""
    full = []
    for rec in records:
        full.append({**rec, "reference_gloss": gloss(client, cfg, rec["reference"]),
                     "candidate_gloss": gloss(client, cfg, rec["candidate"])})
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(render_page(full, page_key))
    return full


PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Faithfulness labels</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600&family=Noto+Sans+Math&family=Noto+Sans+Mono&family=Inter:wght@400;600;700&display=swap" rel="stylesheet">
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/KaTeX/0.16.9/katex.min.css">
<script defer src="https://cdnjs.cloudflare.com/ajax/libs/KaTeX/0.16.9/katex.min.js"></script>
<script defer src="https://cdnjs.cloudflare.com/ajax/libs/KaTeX/0.16.9/contrib/auto-render.min.js"></script>
<style>
:root { --bg:#0f1115; --panel:#171a21; --panel2:#1d212a; --line:#2b313c; --fg:#e6e8ec; --muted:#9aa3b2;
  --accent:#7aa2f7; --good:#3fb27f; --bad:#e5604f; --unsure:#d7a43a; --kw:#c792ea; --sym:#89ddff; --ty:#ffcb6b;
  --const:#82aaff; --num:#f78c6c; --hyp:#c3e88d;
  --mono:"JetBrains Mono","Noto Sans Mono","Noto Sans Math","DejaVu Sans Mono",Menlo,monospace; }
* { box-sizing:border-box; }
html, body { margin:0; height:100%; background:var(--bg); color:var(--fg); font:16px/1.5 Inter, system-ui, sans-serif; }
body { display:flex; flex-direction:column; }
header { display:flex; align-items:center; gap:14px; padding:10px 20px; border-bottom:1px solid var(--line); background:var(--panel); }
header .title { font-weight:700; }
.bar { flex:1; display:flex; align-items:center; gap:10px; }
.track { flex:1; height:8px; background:var(--panel2); border-radius:99px; overflow:hidden; }
.fill { height:100%; width:0; background:linear-gradient(90deg, var(--accent), var(--good)); transition:width .25s; }
.count { color:var(--muted); font-variant-numeric:tabular-nums; white-space:nowrap; }
button { font:inherit; color:var(--fg); background:var(--panel2); border:1px solid var(--line); border-radius:8px; padding:6px 12px; cursor:pointer; }
button:hover { border-color:var(--accent); }
main { flex:1; overflow:auto; padding:22px 28px 12px; max-width:1500px; width:100%; margin:0 auto; }
.lid { color:var(--muted); font-size:13px; letter-spacing:.04em; }
.english { font-size:21px; line-height:1.55; background:var(--panel); border:1px solid var(--line); border-radius:12px; padding:16px 20px; margin:8px 0 18px; }
.pair { display:grid; grid-template-columns:1fr 1fr; gap:18px; }
@media (max-width:900px) { .pair { grid-template-columns:1fr; } }
.side h3 { margin:0 0 6px; font-size:13px; text-transform:uppercase; letter-spacing:.08em; color:var(--muted); }
pre.lean { margin:0; font-family:var(--mono); font-size:15px; line-height:1.6; white-space:pre-wrap; overflow-wrap:anywhere;
  background:var(--panel); border:1px solid var(--line); border-radius:12px; padding:14px 16px; min-height:5em; }
.gloss { color:var(--muted); font-size:15px; margin:10px 2px 0; }
.gloss b { color:var(--fg); font-weight:600; }
.gloss code.g { font-family:var(--mono); font-size:13px; background:var(--panel2); border-radius:4px; padding:0 4px; color:var(--fg); }
.k { color:var(--kw); } .s { color:var(--sym); } .t { color:var(--ty); } .c { color:var(--const); } .n { color:var(--num); } .h { color:var(--hyp); }
.labels { display:grid; grid-template-columns:repeat(3, 1fr); gap:14px; margin:22px 0 12px; }
.labels button { padding:16px; font-size:19px; font-weight:600; border-width:2px; border-radius:12px; }
.labels button kbd { margin-left:8px; }
.labels button[data-label=faithful].chosen { background:rgba(63,178,127,.18); border-color:var(--good); }
.labels button[data-label=unfaithful].chosen { background:rgba(229,96,79,.18); border-color:var(--bad); }
.labels button[data-label=unsure].chosen { background:rgba(215,164,58,.18); border-color:var(--unsure); }
textarea { width:100%; min-height:64px; resize:vertical; font:15px/1.4 Inter, system-ui, sans-serif; color:var(--fg);
  background:var(--panel); border:1px solid var(--line); border-radius:10px; padding:10px 12px; }
textarea:focus { outline:none; border-color:var(--accent); }
.nav { display:flex; justify-content:space-between; align-items:center; margin-top:10px; }
footer { padding:8px 20px; border-top:1px solid var(--line); background:var(--panel); color:var(--muted); font-size:13px; display:flex; gap:18px; flex-wrap:wrap; }
kbd { font-family:var(--mono); font-size:12px; background:var(--panel2); border:1px solid var(--line); border-bottom-width:2px; border-radius:5px; padding:0 6px; color:var(--fg); }
.overlay { position:fixed; inset:0; background:rgba(5,6,8,.72); display:none; align-items:flex-start; justify-content:center; padding:5vh 16px; z-index:10; overflow:auto; }
.overlay.open { display:flex; }
.sheet { background:var(--panel); border:1px solid var(--line); border-radius:14px; padding:20px 24px; max-width:980px; width:100%; }
.sheet h2 { margin:0 0 12px; }
#list ol { list-style:none; margin:0; padding:0; display:grid; grid-template-columns:repeat(auto-fill, minmax(280px, 1fr)); gap:8px; }
#list .jump { width:100%; text-align:left; display:flex; gap:10px; align-items:center; }
#list .snip { flex:1; color:var(--muted); font-size:13px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
#list .state { width:12px; height:12px; border-radius:99px; background:var(--line); flex:none; }
#list .state.faithful { background:var(--good); } #list .state.unfaithful { background:var(--bad); } #list .state.unsure { background:var(--unsure); }
#list .jump.current { border-color:var(--accent); }
.cheat { display:grid; grid-template-columns:repeat(auto-fill, minmax(290px, 1fr)); gap:6px 22px; }
.cheat div { padding:5px 0; border-bottom:1px solid var(--line); font-size:14px; }
.cheat code { font-family:var(--mono); color:var(--sym); }
#done { text-align:center; padding:12vh 20px; display:none; }
#done.show { display:block; }
#done h1 { font-size:34px; margin:0 0 10px; }
#done .big { font-size:18px; padding:12px 22px; margin:8px; }
.toast { position:fixed; bottom:56px; left:50%; transform:translateX(-50%); background:var(--panel2); border:1px solid var(--accent);
  border-radius:10px; padding:10px 16px; display:none; z-index:20; }
.toast.show { display:block; }
</style></head><body>
<header>
  <span class="title">Faithfulness labels</span>
  <div class="bar"><div class="track"><div class="fill" id="fill"></div></div><span class="count" id="count">0 of __N__</span></div>
  <button id="open-list" title="List view (L)">List <kbd>L</kbd></button>
  <button id="open-help" title="Lean notation (?)">Lean help <kbd>?</kbd></button>
  <button id="export" title="Download labels.csv">Export labels.csv</button>
  <button id="export-notes" title="Download notes.csv">Notes.csv</button>
</header>
<main>
  <section id="item">
    <div class="lid" id="lid"></div>
    <div class="english" id="english"></div>
    <div class="pair">
      <div class="side"><h3>Reference</h3><pre class="lean" id="reference"></pre><p class="gloss"><b>Plain English:</b> <span id="reference-gloss"></span></p></div>
      <div class="side"><h3>Candidate</h3><pre class="lean" id="candidate"></pre><p class="gloss"><b>Plain English:</b> <span id="candidate-gloss"></span></p></div>
    </div>
    <div class="labels">
      <button data-label="faithful">Faithful<kbd>F</kbd></button>
      <button data-label="unfaithful">Unfaithful<kbd>U</kbd></button>
      <button data-label="unsure">Unsure<kbd>S</kbd></button>
    </div>
    <textarea id="notes" placeholder="Notes for this item (optional). Press N to type here, Esc to leave."></textarea>
    <div class="nav"><button id="prev">&larr; Previous</button><span class="count" id="saved"></span><button id="next">Next &rarr;</button></div>
  </section>
  <section id="done">
    <h1>All __N__ items labeled.</h1>
    <p>Thank you. Your labels are saved in this browser; export them to finish.</p>
    <button class="big" id="done-export">Export labels.csv</button>
    <button class="big" id="done-notes">Export notes.csv</button>
    <button class="big" id="done-review">Review items</button>
  </section>
</main>
<footer>
  <span><kbd>F</kbd> faithful</span><span><kbd>U</kbd> unfaithful</span><span><kbd>S</kbd> unsure</span>
  <span><kbd>&larr;</kbd> <kbd>&rarr;</kbd> previous / next</span><span><kbd>N</kbd> notes</span><span><kbd>Esc</kbd> leave notes / close</span>
  <span><kbd>L</kbd> list</span><span><kbd>?</kbd> Lean help</span><span>Autosaved in this browser.</span>
</footer>
<div class="overlay" id="list"><div class="sheet"><h2>All items</h2><ol>
__LIST__
</ol></div></div>
<div class="overlay" id="help"><div class="sheet"><h2>Lean notation</h2><div class="cheat">
  <div><code>∀ x, P x</code> for every x, P x holds</div>
  <div><code>∃ x, P x</code> there is some x with P x</div>
  <div><code>∃! x, P x</code> there is exactly one such x</div>
  <div><code>P → Q</code> if P then Q (also a function type)</div>
  <div><code>P ↔ Q</code> P if and only if Q</div>
  <div><code>¬ P</code> not P; <code>a ≠ b</code> means ¬ (a = b)</div>
  <div><code>P ∧ Q</code>, <code>P ∨ Q</code> and, or</div>
  <div><code>ℕ ℤ ℚ ℝ ℂ</code> naturals (from 0), integers, rationals, reals, complex numbers</div>
  <div><code>(n : ℤ)</code> or <code>↑n</code> the coercion: n viewed in a bigger type</div>
  <div><code>(2 : ℝ)</code> a type ascription: this 2 is a real number</div>
  <div><code>Set α</code> a set of elements of type α; <code>x ∈ s</code>, <code>s ⊆ t</code></div>
  <div><code>Finset α</code> a finite set; <code>Finset.range n</code> is {0, ..., n-1}</div>
  <div><code>s.card</code> or <code>Finset.card s</code> the number of elements of a finite set</div>
  <div><code>∑ i ∈ s, f i</code>, <code>∏ i ∈ s, f i</code> sum and product over a finite set</div>
  <div><code>Function.Injective f</code> one-to-one; <code>Function.Surjective f</code> onto</div>
  <div><code>Filter.Tendsto f l₁ l₂</code> f tends to l₂ along l₁ (limits)</div>
  <div><code>atTop</code> the filter "n goes to infinity"</div>
  <div><code>𝓝 a</code> the neighbourhoods of a, as in "x tends to a"</div>
  <div><code>a ≡ b [ZMOD n]</code> a is congruent to b modulo n (integers)</div>
  <div><code>Polynomial R</code> or <code>R[X]</code> polynomials over R; <code>X</code> the variable</div>
  <div><code>p.degree</code>, <code>p.roots</code>, <code>Polynomial.derivative p</code> degree, roots, derivative</div>
  <div><code>[Group G]</code>, <code>[Field K]</code> square brackets: G is assumed to carry this structure</div>
  <div><code>{x : ℝ}</code> curly braces: an implicit argument Lean fills in</div>
  <div><code>theorem t (x : ℝ) (h : 0 &lt; x) : P x</code> everything before the last colon is given (variables and hypotheses h); after it is what is claimed</div>
  <div><code>(h₁ : a) (h₂ : b) : c</code> reads "if a and b, then c"</div>
  <div><code>:= by sorry</code> the proof is left out; only the statement matters here</div>
</div></div></div>
<div class="toast" id="toast"></div>
<script id="data" type="application/json">__DATA__</script>
<script>
const ITEMS = JSON.parse(document.getElementById("data").textContent);
const KEY = "labels:__KEY__", NOTES = "notes:__KEY__", POS = "pos:__KEY__";
function load(k, d) { try { return JSON.parse(localStorage.getItem(k) || "null") ?? d; } catch (e) { return d; } }
function store(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) {} }
let labels = load(KEY, {}), notes = load(NOTES, {}), pos = Math.min(load(POS, 0) || 0, ITEMS.length - 1);
let celebrated = Object.keys(labels).length >= ITEMS.length;
const $ = id => document.getElementById(id);

function esc(s) { return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;"); }
const KW = new Set(["theorem","lemma","def","fun","by","sorry","let","in","have","show","from","with","match","if","then","else",
  "Type","Prop","Sort","open","variable","where","instance","structure","class","example","noncomputable","set_option"]);
function lean(src) {
  // Colour one Lean statement on its own; nothing here looks at the other statement.
  const re = /([A-Za-z_][\w.'₀-₉]*)|(\d+(?:\.\d+)?)|([∀∃→↔¬∧∨λ↦∈∉⊆⊂∩∪∑∏≤≥≠≡∣×•∘⁻¹↑∞]|:=|->|<->)|([ℕℤℚℝℂ𝓝])|(\s+)|(.)/gu;
  let out = "", m, prevH = false;
  while ((m = re.exec(src)) !== null) {
    const [tok, id, num, sym, ty] = m;
    if (id) {
      if (KW.has(id)) out += `<span class="k">${esc(id)}</span>`;
      else if (/^h[\w₀-₉']*$/.test(id) && prevH) out += `<span class="h">${esc(id)}</span>`;
      else if (/^[A-Z]/.test(id) || id.includes(".")) out += `<span class="c">${esc(id)}</span>`;
      else out += esc(id);
    } else if (num) out += `<span class="n">${num}</span>`;
    else if (sym) out += `<span class="s">${esc(sym)}</span>`;
    else if (ty) out += `<span class="t">${ty}</span>`;
    else out += esc(tok);
    if (!/^\s+$/.test(tok)) prevH = tok === "(";
  }
  return out;
}
function md(s) {
  // Glosses are shown as written; only **bold** and `code` marks are turned into formatting.
  return esc(s).replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>").replace(/`([^`]+)`/g, '<code class="g">$1</code>');
}
function mathify(el) {
  if (window.renderMathInElement) renderMathInElement(el, { delimiters: [
    { left: "$$", right: "$$", display: true }, { left: "$", right: "$", display: false },
    { left: "\\(", right: "\\)", display: false }, { left: "\\[", right: "\\]", display: true }], throwOnError: false });
}
function toast(msg) { const t = $("toast"); t.textContent = msg; t.classList.add("show"); clearTimeout(toast.t); toast.t = setTimeout(() => t.classList.remove("show"), 2600); }
function done() { return ITEMS.filter(r => labels[r.label_id]).length; }

function show() {
  const r = ITEMS[pos];
  $("item").style.display = ""; $("done").classList.remove("show");
  $("lid").textContent = r.label_id + "  ·  item " + (pos + 1) + " of " + ITEMS.length;
  $("english").textContent = r.english; mathify($("english"));
  $("reference").innerHTML = lean(r.reference); $("candidate").innerHTML = lean(r.candidate);
  $("reference-gloss").innerHTML = md(r.reference_gloss); $("candidate-gloss").innerHTML = md(r.candidate_gloss);
  $("notes").value = notes[r.label_id] || "";
  store(POS, pos); refresh();
}
function refresh() {
  const n = done();
  $("count").textContent = n + " of " + ITEMS.length;
  $("fill").style.width = (100 * n / ITEMS.length) + "%";
  const cur = labels[ITEMS[pos].label_id];
  for (const b of document.querySelectorAll(".labels button")) b.classList.toggle("chosen", b.dataset.label === cur);
  $("saved").textContent = cur ? "Saved: " + cur : "Not labeled yet";
  document.querySelectorAll("#list .jump").forEach((b, i) => {
    const l = labels[ITEMS[i].label_id];
    b.querySelector(".state").className = "state" + (l ? " " + l : "");
    b.classList.toggle("current", i === pos);
  });
}
function setLabel(l) {
  labels[ITEMS[pos].label_id] = l; store(KEY, labels); refresh();
  if (done() === ITEMS.length && !celebrated) { celebrated = true; finish(); return; }
  setTimeout(() => { const next = nextOpen(); if (next !== null) { pos = next; show(); } }, 220);
}
function nextOpen() {
  for (let k = 1; k <= ITEMS.length; k++) { const i = (pos + k) % ITEMS.length; if (!labels[ITEMS[i].label_id]) return i; }
  return pos < ITEMS.length - 1 ? pos + 1 : null;
}
function move(d) { pos = Math.max(0, Math.min(ITEMS.length - 1, pos + d)); show(); }
function finish() { $("item").style.display = "none"; $("done").classList.add("show"); refresh(); }
function download(name, text) {
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([text], { type: "text/csv" })); a.download = name; a.click();
}
function exportLabels() {
  const rows = ["label_id,label", ...ITEMS.map(r => r.label_id + "," + (labels[r.label_id] || ""))];
  download("labels.csv", rows.join("\n") + "\n");
  const n = done(); toast(n === ITEMS.length ? "labels.csv downloaded: all " + n + " items" : "labels.csv downloaded: " + n + " of " + ITEMS.length + " labeled so far");
}
function exportNotes() {
  const q = s => '"' + String(s).replace(/"/g, '""') + '"';
  const rows = ["label_id,note", ...ITEMS.filter(r => notes[r.label_id]).map(r => r.label_id + "," + q(notes[r.label_id]))];
  download("notes.csv", rows.join("\n") + "\n");
}
function toggle(id, on) { const o = $(id); o.classList.toggle("open", on ?? !o.classList.contains("open")); }

document.querySelectorAll(".labels button").forEach(b => b.onclick = () => setLabel(b.dataset.label));
$("prev").onclick = () => move(-1); $("next").onclick = () => move(1);
$("export").onclick = exportLabels; $("done-export").onclick = exportLabels;
$("export-notes").onclick = exportNotes; $("done-notes").onclick = exportNotes;
$("done-review").onclick = () => { pos = 0; show(); };
$("open-list").onclick = () => toggle("list"); $("open-help").onclick = () => toggle("help");
document.querySelectorAll(".overlay").forEach(o => o.onclick = e => { if (e.target === o) o.classList.remove("open"); });
document.querySelectorAll("#list .jump").forEach(b => b.onclick = () => { pos = +b.dataset.i; toggle("list", false); show(); });
$("notes").oninput = e => { const id = ITEMS[pos].label_id; if (e.target.value) notes[id] = e.target.value; else delete notes[id]; store(NOTES, notes); };
document.addEventListener("keydown", e => {
  if (e.target === $("notes")) { if (e.key === "Escape") $("notes").blur(); return; }
  if (e.metaKey || e.ctrlKey || e.altKey) return;
  const k = e.key.toLowerCase();
  if (k === "escape") { toggle("list", false); toggle("help", false); return; }
  if (k === "?" || (k === "/" && e.shiftKey)) { toggle("help"); return; }
  if (k === "l") { toggle("list"); return; }
  if ($("help").classList.contains("open") || $("list").classList.contains("open")) return;
  if ($("done").classList.contains("show") && (k === "arrowleft" || k === "arrowright")) { show(); return; }
  if (k === "f") setLabel("faithful");
  else if (k === "u") setLabel("unfaithful");
  else if (k === "s") setLabel("unsure");
  else if (k === "arrowleft") move(-1);
  else if (k === "arrowright") move(1);
  else if (k === "n") { e.preventDefault(); $("notes").focus(); }
});
window.addEventListener("load", () => mathify($("english")));
if (celebrated) finish(); else show();
</script></body></html>
"""
