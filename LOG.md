# LOG

## Now

- **Chunk:** 1 of 7 done (setup and data)
- **Status:** ready for chunk 2
- **Next:** in Claude Code, type "Start chunk 2"
- **Spent so far:** $0 of $300
- **Waiting on Neel:** approve `.claude/settings.json` (the pre-approved command list); Claude Code's auto mode blocked Claude from writing it, so Neel creates it or approves the write
- **Parked ideas:** see the chunk 1 entry

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
