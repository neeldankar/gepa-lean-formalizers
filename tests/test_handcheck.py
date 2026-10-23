"""Chunk 6 hand-check sample: makeup, cap, pairing across arms, determinism, blindness, and the join."""
import csv
import json

from src.analysis import hand_check, read_labels
from src.handcheck import CORE, build_sample, page_records, summary
from src.scoring.labeling import FIELDS, render_page

ITEMS = [f"t{i:03d}" for i in range(60)]


def row(arm, item, seed, compiled=True, certified=False, ref="faithful", dataset="test"):
    return {"arm": arm, "run_id": f"{arm}_s{seed}" if seed is not None else None, "gepa_seed": seed, "dataset": dataset,
            "item_id": item, "sample": 0, "compiled": compiled, "certified": certified, "ref_verdict": ref if compiled else None,
            "normalized": f"theorem X ({arm} {item} {seed}) : True := by sorry" if compiled else None,
            "judge_score": int(compiled), "judge_missing": False}


def fake_rows(n_dis=5, every_nth_fails=3):
    rows = []
    for k, item in enumerate(ITEMS):
        for arm in CORE:
            for seed in ((0, 1, 2) if arm in ("B", "D") else (None,)):
                rows.append(row(arm, item, seed, compiled=(k + CORE.index(arm)) % every_nth_fails != 0))
    for r in [r for r in rows if r["compiled"]][:n_dis]:
        r.update(certified=True, ref_verdict="unfaithful")
    rows.append(row("E", ITEMS[0], None, certified=True, ref="unfaithful"))  # not a core arm
    rows.append(row("A", "m1", None, certified=True, ref="unfaithful", dataset="minif2f"))  # not test
    return rows


def test_makeup_pairing_and_fixed_labels():
    sample = build_sample(fake_rows(), seed=0)
    s = summary(sample)
    assert s["disagreement_part"] == 5 and 100 <= s["shown"] <= 103
    assert all(x["arm"] in CORE for x in sample) and len({x["label_id"] for x in sample}) == len(sample)
    rand = [x for x in sample if "random" in x["parts"]]
    for item in {x["item_id"] for x in rand}:
        arms = [x["arm"] for x in rand if x["item_id"] == item]
        assert sorted(arms) == sorted(CORE)  # each random item once in every core arm, one seed for B and D
    for x in sample:
        assert x["shown"] == ("fixed_label" not in x)
    assert any(not x["shown"] for x in rand) and all("random" in x["parts"] for x in sample if not x["shown"])
    shown = [x["shown"] for x in sample]
    assert shown == sorted(shown, reverse=True)  # page entries first


def test_disagreement_cap_and_determinism():
    rows = fake_rows(n_dis=40)
    a, b = build_sample(rows, seed=0), build_sample(rows, seed=0)
    assert a == b and summary(a)["disagreement_part"] == 25
    assert build_sample(rows, seed=1) != a


def test_page_shows_only_whitelisted_fields(tmp_path):
    rows = fake_rows()
    sample = build_sample(rows, seed=0)
    items = {i: {"informal_stmt": f"English {i}", "formal_stmt": f"theorem r_{i} : True := by sorry"} for i in ITEMS}
    records = page_records(sample, rows, items, lambda s: s)
    assert len(records) == summary(sample)["shown"] and all(set(r) == {"label_id", "english", "reference", "candidate"} for r in records)
    page = render_page([{**r, "reference_gloss": "g", "candidate_gloss": "g"} for r in records], "k")
    data = json.loads(page.split('<script id="data" type="application/json">')[1].split("</script>")[0])
    assert all(set(d) == set(FIELDS) for d in data)
    for word in ("gepa_seed", "run_id", '"arm"', "judge_score", "ref_verdict", "certified"):
        assert word not in page


def test_fixed_labels_join_and_pair(tmp_path):
    rows = fake_rows()
    sample = build_sample(rows, seed=0)
    (tmp_path / "sample.jsonl").write_text("".join(json.dumps(s) + "\n" for s in sample))
    with open(tmp_path / "labels.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["label_id", "label"])
        for s in sample:
            if s["shown"]:
                w.writerow([s["label_id"], "faithful"])
    labeled = read_labels(tmp_path / "labels.csv", tmp_path / "sample.jsonl")
    assert all(x["label"] == "unfaithful" for x in labeled if not x["shown"])
    assert all(x["label"] == "faithful" for x in labeled if x["shown"])
    out = hand_check(rows, labeled, resamples=50, seed=0)
    assert out["random_items_paired"] == out["random_items"] and out["items_dropped"] == 0


def storage_keys(page):
    import re
    line = re.search(r"const KEY = [^;]*;", page).group(0)
    return set(re.findall(r'"((?:labels|notes|pos):[^"]+)"', line))


def test_chunk6_storage_keys_differ_from_the_pilot_pages():
    """All file:// pages share one browser origin, so a new key keeps pilot labels out of chunk 6."""
    from scripts.chunk6 import OUT, PAGE_KEY
    pilot = {f"{p}:{k}" for p in ("labels", "notes", "pos") for k in ("chunk4-pilot", "chunk2-demo")}
    rendered = storage_keys(render_page([], PAGE_KEY))
    built_page = (OUT / "labeling.html").read_text()
    built = storage_keys(built_page)
    assert rendered == built == {"labels:chunk6-handcheck", "notes:chunk6-handcheck", "pos:chunk6-handcheck"}
    assert not built & pilot and not built & storage_keys((OUT.parent / "chunk4/labeling.html").read_text())
    assert 'download("labels.csv"' in built_page
