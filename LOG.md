# LOG

## Now

- **Chunk:** 2 of 7 done (scoring)
- **Status:** ready for chunk 3
- **Next:** in Claude Code, type "Start chunk 3"
- **Spent so far:** $0.03 of $300 (all in chunk 2)
- **Waiting on Neel:** three decisions in the chunk 2 entry's Parked list (certificates and trivially true conjuncts; the 4 references that need autoImplicit; arm C's exact prompt). None blocks chunk 3.
- **Parked ideas:** see the chunk 1 and chunk 2 entries

## Entries

Newest first. One entry per chunk session and per run, including failed or discarded runs.

Template:

```
### YYYY-MM-DD · chunk N · short title
- Did:
- Numbers: (from <file>.json; subagent check: match / mismatch)
- Cost: $X this entry, $Y total
- Problems:
- Next:
```

### 2026-10-18 · chunk 2 · scoring

- **Did:** prereg.md edits approved by Neel (Changes items 7, 8, 10 plus consistency fixes; commit e9eeb8a). Wrote `.claude/settings.json` (Neel approved). Re-ran the miniF2F load with the scripted `∑/∏ x in s` binder rewrite. Built `src/scoring/`: extraction, our comment stripper, normalization, compile with `set_option autoImplicit false in`, Together client with cache, cost log and budget stop (`src/llm.py`), both judges, equivalence certificates, truth score, memorization check, labeling page. AXLE wrapper gained `normalize`. Entry script `scripts/chunk2.py`. Tests: 86 pass (golden and AXLE tests run live against the cache).
- **Numbers** (from `runs/chunk1/summary.json` and `runs/chunk2/summary.json`; subagent check: match on every count, its numbers in `runs/chunk2/subagent_check.json`):
  - miniF2F after the binder rewrite: 243 usable, 1 dropped of 244. The rewrite applied to 31 items, all of them the ones that failed in chunk 1, and 31 now compile. Still failing: minif2f_amc12a_2020_p15 (lean.unknownIdentifier): Unknown constant `Complex.abs`
).
  - References compiled with autoImplicit off (information only): 363/367
    - pnv_025: -:7:70-7:71: error(lean.unknownIdentifier): Unknown identifier `F`
    - pnv_207: -:7:71-7:72: error(lean.unknownIdentifier): Unknown identifier `F`
    - pnv_208: -:7:70-7:71: error(lean.unknownIdentifier): Unknown identifier `F`
    - pnv_280: -:8:8-8:11: error(lean.unknownIdentifier): Unknown identifier `f_a`
  - Duplicate Rudin_exercise_4_8a (pnv_168, pnv_351, splits ['test', 'test']): identical False, differs in ['informal_stmt', 'formal_stmt']
  - Stripper contest: ours 14/14, AXLE remove_comments 13/14; winner: ours
    - AXLE failed 'single primed name then comment': output "theorem t (x' : ℕ) : x' = x' := rfl -- the judge should say faithful"
  - Golden cases: 14/14 pass; certificates: on

  | Case | Expected | Got | Pass |
  | --- | --- | --- | --- |
  | exact copy | compiled=true; certified=true; truth_label=faithful | compiled=true; certified=true; truth_label=faithful | yes |
  | a < b written as b > a | compiled=true; certified=true; truth_label=faithful | compiled=true; certified=true; truth_label=faithful | yes |
  | reordered hypotheses | compiled=true; certified=true; truth_label=faithful | compiled=true; certified=true; truth_label=faithful | yes |
  | hypothesis dropped | compiled=true; certified=false; judge_verdict=unfaithful; truth_label=unfaithful | compiled=true; certified=false; judge_verdict=unfaithful; truth_label=unfaithful | yes |
  | ℕ where the text says integers | compiled=true; certified=false; truth_label=unfaithful | compiled=true; certified=false; truth_label=unfaithful | yes |
  | swapped quantifier | compiled=true; certified=false; truth_label=unfaithful | compiled=true; certified=false; truth_label=unfaithful | yes |
  | comment claiming faithfulness | compiled=true; certified=false; truth_label=unfaithful; never_reaches_judge=["faithful translation", "verified by experts", "answer faithful"] | compiled=true; certified=false; truth_label=unfaithful; never_reaches_judge=["faithful translation", "verified by experts", "answer faithful"] | yes |
  | does not compile | compiled=false; judge_score=0; truth_label=unfaithful | compiled=false; judge_score=0; truth_label=unfaithful | yes |
  | invented dotted name Nat.IsGoodPrime | compiled=false; judge_score=0; truth_label=unfaithful | compiled=false; judge_score=0; truth_label=unfaithful | yes |
  | invented plain name (autoImplicit off) | compiled=false; judge_score=0; truth_label=unfaithful | compiled=false; judge_score=0; truth_label=unfaithful | yes |
  | long ReForm-style output | compiled=true; certified=true; truth_label=faithful; normalized_contains=(h : a > 1) | compiled=true; certified=true; truth_label=faithful; normalized_contains=(h : a > 1) | yes |
  | no Lean in the output | format_failure=true; compiled=false; judge_score=0; truth_label=unfaithful | format_failure=true; compiled=false; judge_score=0; truth_label=unfaithful | yes |
  | true but unrelated statement | compiled=true; certified=false; truth_label=unfaithful; r2c_discarded=true | compiled=true; certified=false; truth_label=unfaithful; r2c_discarded=true | yes |
  | string literal with -- survives stripping | compiled=true; normalized_contains="a--b".length = 4; never_reaches_judge=["trailing comment"] | compiled=true; normalized_contains="a--b".length = 4; never_reaches_judge=["trailing comment"] | yes |

  - Judge cost per call (chunk 2, $0.0296 over 49 paid calls):
    - opt_judge (openai/gpt-oss-120b): 10 calls, $0.000304 per call
    - ref_judge (deepseek-ai/DeepSeek-V4.1-Flash): 10 calls, $0.000751 per call
    - probe (zai-org/GLM-5.3-Flash): 3 calls, $0.000114 per call
    - gloss (zai-org/GLM-5.3-Flash): 26 calls, $0.000721 per call
  - Memorization index: 644 distinct statements; sources {'ProofNet-Verified': {'rows': 367, 'keys': 367}, 'ProofNet#': {'rows': 371, 'keys': 371}, 'ProofNet-lean4 (6deae98)': {'rows': 374, 'keys': 360}, 'ProofNet (Lean 4.28 port)': {'rows': 367, 'keys': 353}}; skipped {'ProofNet (original)': 'Lean 3 only'}; train references matching themselves: 50/50
- **Choices the spec left open:**
  - Stripper: ours. AXLE's `remove_comments` treats `'` as a string quote, so after a single primed name (`x'`) it keeps a trailing comment, exactly the injection the stripper exists to stop.
  - Docstrings are removed by our stripper directly; AXLE `normalize_doc_comments` is used only in the memorization check. After extracting one declaration there is no docstring left for normalize to convert.
  - Memorization key: AXLE `normalize` (its defaults plus `normalize_doc_comments`), no comments, fixed name, `:= by sorry`, all whitespace removed (so `x*y` matches `x * y`). The original ProofNet is Lean 3 only and skipped; its two Lean 4 ports from ProofNet-Verified's repo are used. 14 rows in each port are `instance` declarations, not theorems, and get no key.
  - Certificates: tactics `exact hcert`, `simpa using hcert`, `intros; simp_all`, `intros; aesop`, `intros; tauto`; the no-hypothesis run replaces `hcert` with `(hcert : True)` so a tactic that ignores `hcert` cannot pass the check by an unknown-name error. `Type*` becomes one shared `Type u`. Certificates passed every golden case in well under the 3-hour timebox, so `certificates: true`.
  - Judges (placeholders until the pilot): optimization `openai/gpt-oss-120b`, reference `deepseek-ai/DeepSeek-V4.1-Flash`. Gloss model `zai-org/GLM-5.3-Flash`: Llama-4-Scout, Mistral-Small, Ministral, Gemma-4 and gpt-oss-20b are not serverless on Together. GLM thinks even when asked not to, so glosses get 8000 tokens and one retry.
  - A judge reply without valid JSON gets one re-ask, then counts as `unparseable` (not faithful).
- **Parked (for Neel, not built):**
  - Certificates prove logical equivalence, so a candidate that adds an always-true conjunct (golden case `"a--b".length = 4`) is certified faithful while both judges say unfaithful ("Adding extra conclusion"). Under the prereg the certificate wins. The chunk 6 hand-check samples these disagreements, but Neel may want a rule before the freeze.
  - 4 references compile only with autoImplicit on (`F` in pnv_025, pnv_207, pnv_208; `f_a` in pnv_280; splits test, test, val, train). A candidate written in the same style fails to compile under Changes item 10.
  - Arm C's prompt in prereg.md is "Think step by step to translate the mathematical problem in natural language to Lean 4"; ReForm's repo (`lean_plugins/generate.py`) uses the same text plus ", and verify the consistency." followed by the problem. Decide before chunk 3 builds the generation client.
- **Cost:** $0.0296 this entry (49 paid calls), $0.0296 total
- **Problems:** the first judge smoke call used Rudin_exercise_1_2 (pnv_149), a **test** item: one optimization-judge and one reference-judge call on a hand-written candidate, $0.0004, no formalizer output and no score kept. Every later dev and golden call used train items only, and the golden runner now refuses non-train items. Two GLM probe calls bypassed the client and were added to `runs/costs.jsonl` by hand from their reported token usage.
- **Next:** chunk 3

### 2026-10-17 · chunk 1 · setup and data

- **Did:** repo skeleton, `config.yaml`, secret scan (`scripts/secret_scan.py`, installed as pre-commit and pre-push hooks by `scripts/install_hooks.sh`), AXLE `check` wrapper (`src/axle_check.py`: disk cache, retries, outages kept apart), ProofNet-Verified and miniF2F loaders, seeded stratified split. Entry script `scripts/chunk1.py`. No old lean-gepa grader, so the wrapper is new. Tests: 27 pass (3 live AXLE).
- **Numbers** (from `runs/chunk1/summary.json`; subagent check: match, its numbers in `runs/chunk1/subagent_check.json`: compiled 367, sizes {'train': 50, 'val': 70, 'test': 247}, miniF2F usable 212, dropped 32, per-textbook table identical):

- ProofNet-Verified reference compile: 367/367 ({'ok': 367})
- Split sizes (seed 0): {'train': 50, 'val': 70, 'test': 247}; kept together: [['pnv_168', 'pnv_351']]

| Textbook | Total | Train | Val | Test |
| --- | --- | --- | --- | --- |
| Artin | 28 | 4 | 5 | 19 |
| Axler | 26 | 3 | 5 | 18 |
| Dummit Foote | 87 | 12 | 17 | 58 |
| Herstein | 47 | 6 | 9 | 32 |
| Ireland Rosen | 21 | 3 | 4 | 14 |
| Munkres | 60 | 8 | 11 | 41 |
| Pugh | 14 | 2 | 3 | 9 |
| Putnam | 12 | 2 | 2 | 8 |
| Rudin | 56 | 8 | 11 | 37 |
| Shakarchi | 16 | 2 | 3 | 11 |

- miniF2F: 212 usable, 32 dropped of 244 ({'ok': 212, 'lean_error': 32})
  - 31 items: "unexpected token 'in'; expected ','\n"
  - 1 items: '(lean.unknownIdentifier): Unknown constant `Comple'

- **Choices the spec left open:**
  - ProofNet-Verified pinned at commit `160414332dc1`, miniF2F at HF revision `5def31834852`. Raw downloads kept in `data/raw/`.
  - Ids are `pnv_<index>` because `name` is not unique: Rudin_exercise_4_8a is listed twice (index 168 and 351, slightly different statements). The split keeps both copies in one split by swapping with a same-textbook item, so counts and strata are unchanged.
  - Per-textbook quotas use largest-remainder rounding; split seed 0 in `config.yaml`.
  - AXLE statuses: ok, lean_error, timeout, resource (failures), outage (AxleIsUnavailable, RateLimited, Internal and Runtime errors after 3 retries with backoff; never cached or scored). Compile pass = AXLE `okay`.
  - miniF2F header = the text before the docstring; reference = the theorem with `sorry` appended. 31 of the 32 drops use the old `∑ x in s` syntax that this Mathlib no longer parses. Not fixed, per the spec.
  - Python 3.12 venv via uv (system Python is 3.14). `.env` lines are indented; the loader tolerates that.
- **Parked (for chunk 2 to consider, not built):**
  - AXLE's Lean environment has `autoImplicit` on: an unknown identifier in a candidate can compile as an auto-bound variable. Chunk 2 may want `set_option autoImplicit false` in the compile check (scoring decision, needs Neel).
  - The `axiom-axle` 1.9.0 Python package ships `axle.remove_comments` (prereg Changes item 7 says AXLE has none). The prereg still calls for our own tested stripper; it could be a cross-check.
- **Cost:** $0 this entry (AXLE only, 611 calls), $0 total
- **Problems:** `.claude/settings.json` not written (see Waiting on Neel).
- **Next:** chunk 2

### 2026-10-17 · chunk 0 · decisions before starting

- **Did:** wrote `CLAUDE.md`, `CHUNKS.md`, `LOG.md` and `prereg.md` in a claude.ai project chat.
- **Decisions:** Claude Code on Neel's laptop owns all code and runs, and the repo is the only source of truth. Both formalizers run on one rented H100 (RunPod) with vLLM; Qwen3-8B moves off Together, which keeps serving the judges. There is no existing GEPA pipeline, so GEPA comes from the open-source `gepa` library (0.1.4) with a custom adapter, built in chunk 3. Changes to the Oct 17 design doc are listed at the top of `prereg.md`.
- **Cost:** $0 this entry, $0 total
- **Next:** chunk 1
