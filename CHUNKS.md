# Chunks

Seven chunks, each run in one fresh Claude Code session (chunk 5 uses two: launch and check). Neel starts a chunk by typing "Start chunk N". The rules in `CLAUDE.md` apply to every chunk.

| # | Chunk | Neel's time | Unattended | Budget cap |
| --- | --- | --- | --- | --- |
| 1 | Setup and data | 45 min | ~2 h | $0 |
| 2 | Scoring | 20 min | 3-5 h | $10 |
| 3 | Runner | 15 min | 3-5 h | $3 |
| 4 | Pilot and freeze (GPU) | ~2 h | 3-4 h | $30 |
| 5 | Full runs (GPU, overnight) | 10 min | 8-12 h | $180 |
| 6 | Hand-check and analysis | 5-7 h | ~1 h | $5 |
| 7 | Writeup and publish | 1-2 h | 2-3 h | $5 |

Caps add up to $233, under the $300 limit.

---

## Chunk 1: Setup and data

**Neel does first:** create a private GitHub repo containing `CLAUDE.md`, `CHUNKS.md`, `LOG.md` and `prereg.md`, and clone it on the laptop. Create `.env` with `AXLE_API_KEY` (from the AXLE console), `TOGETHER_API_KEY`, and keys for any other model APIs he plans to use. Tell Claude where the old `lean-gepa` grader code is, if he still has it.

**Build:**

1. Repo skeleton: `src/`, `scripts/`, `tests/`, `data/`, `runs/`, `prompts/`, `config.yaml`, `requirements.txt`, `.gitignore` (at least `.env` and `cache/`). Add a secret-scan pre-commit hook.
2. Pre-approve routine commands in `.claude/settings.json` (python, pytest, pip, git without force push, ssh/scp/rsync to the pod) so later sessions don't stop to ask. Neel approves this once.
3. AXLE wrapper around `check` in `lean-4.28.0`: cache, retries, and outages kept apart from Lean errors. Reuse the old grader's wrapper if it's available. Two gotchas from AXLE's docs:
   - A statement ending in `:= by sorry` compiles when `okay` is true. The sorry also shows up in `failed_declarations`; that is not a compile failure.
   - By default AXLE swaps a file's imports for the environment's default header. Keep that default (it's fast and cached). The `open` lines and helper definitions stay in the content.
4. Load ProofNet-Verified (github.com/marcusm117/ProofNet-Verified): id, textbook, English statement, header, helper definitions, reference statement. Save to `data/proofnet_verified.jsonl`.
5. Compile every reference statement (proof replaced by `sorry`) with its header and helpers. Record any failures with their errors.
6. Seeded split stratified by textbook: 50 train, 70 val, 247 test. Save `data/splits.json` with the seed and per-textbook counts.
7. miniF2F (AI-MO version, 244 items): load the English statements and reference statements, compile each in `lean-4.28.0`, and keep the ones that compile as they are. Never hand-fix. Save `data/minif2f.jsonl` and log the dropped count.

**Tests:** split sizes exactly 50/70/247; no id in two splits; the same seed gives the same split; every textbook appears in all three splits roughly in proportion; the AXLE wrapper passes a known-good statement, fails a broken one, and reports a mocked outage as an outage.

**Done when:** tests pass, and `LOG.md` shows the reference compile count (target 367/367, failures listed), the per-textbook split table and the usable miniF2F count, all matched by the subagent check.

---

## Chunk 2: Scoring

**Neel does first:** nothing.

**Build** (in `src/scoring/`):

1. Extraction: pull the final Lean theorem statement out of a model output. Handles several code blocks, no code block (format failure), and ReForm-8B's long reasoning outputs (check its model card for the output format).
2. Normalization before any judge sees an output: turn docstrings into plain comments (AXLE `normalize` with `normalize_doc_comments`), strip all comments with our own tested stripper (AXLE's docs list no comment-removal tool), rename the theorem to a fixed name, and make sure it ends in `:= by sorry`.
3. Compile check with the item's header and helpers.
4. Judge score: the optimization judge sees only the English and the candidate and returns JSON (verdict, reason). The score is 1 only if the statement compiles and the verdict is faithful.
5. Truth score, in this order:
   - compile check (a failure counts as unfaithful; compile rate is reported separately)
   - equivalence certificate: write both statements as closed propositions and try to prove candidate implies reference and reference implies candidate, using a short fixed list of cheap tactics through AXLE. A direction counts only if the same tactic fails to prove the target once the hypothesis is removed. Both directions proved means faithful; anything else means unknown.
   - reference-aware judge on every compiled item: sees the English, the reference and the candidate; returns a verdict, a reason and, if unfaithful, one error tag from ProofNet-Verified's taxonomy
   - truth label = the certificate if there is one, otherwise the judge's verdict
6. Memorization check: normalize (fixed name, no comments, AXLE `normalize`) and count exact matches against ProofNet-Verified, ProofNet# and the original ProofNet. Lean 4 versions only; if a source exists only in Lean 3, skip it and log that.
7. Labeling page: one local HTML file. For each item it shows the English, the reference and the candidate. Each Lean statement gets its own plain-English gloss, written by a cheap model that sees only that one statement and never says whether the two match. Buttons: faithful, unfaithful, unsure. Arm and model are hidden. Labels export to `labels.csv`.

Judge models are placeholders in `config.yaml` until the pilot. For development, use two different non-Qwen model families through Together.

**Timebox:** certificates get 3 hours of work. If they can't pass the golden cases by then, set `certificates: false` in `config.yaml`, log it, and move on. `prereg.md` already covers that case.

**Tests:** a golden set of about 12 hand-built cases made from train items, each with its expected result:

- exact copy of the reference: certificate, faithful
- reordered hypotheses, or `a ≤ b` written as `b ≥ a`: certificate, faithful
- a hypothesis dropped: no certificate, judge says unfaithful
- ℕ where the text says integers: unfaithful
- a swapped quantifier: unfaithful
- a candidate with a comment claiming it's faithful: the comment never reaches the judge
- a candidate that doesn't compile: unfaithful, counted as a compile failure
- a long ReForm-style output: the right statement is extracted
- an output with no Lean in it: format failure
- a true but unrelated statement that automation proves from scratch: no certificate (the hypothesis-removal check catches it)

Plus unit tests for extraction, the comment stripper (line, nested block and doc comments), renaming and the score logic.

**Done when:** all tests pass, and `LOG.md` has the golden table (case, expected, got), the judge cost per call, and whether certificates are on.

---

## Chunk 3: Runner

**Neel does first:** nothing. Like the judges, the reflection model is a placeholder in `config.yaml` until the pilot.

**Build:**

1. Generation client for vLLM's OpenAI-compatible server (base URL in config). Qwen3-8B's thinking mode is set through its chat template's `enable_thinking` flag. ReForm-8B uses its documented prompt and chat format. Temperature, sample count and max output tokens come from config and are identical across arms.
2. GEPA from the open-source `gepa` library, pinned to 0.1.4. Read its adapter interface first, then write a custom adapter with one text component, the instructions:
   - `evaluate` runs the formalizer with the candidate's instructions on a batch and scores each item with the judge score. When asked for traces, it keeps the English, the extracted Lean, Lean's errors, and the judge's verdict and reason.
   - `make_reflective_dataset` turns those into records for the reflection model: the input, the generated Lean, and feedback = Lean errors + judge verdict + judge reason.
   - Call `gepa.optimize` with trainset = the 50 train items, valset = the 70 val items, `max_metric_calls` and `seed` from config, `run_dir` = `runs/<run_id>/gepa` (it resumes from there after a crash), and library defaults for everything else.
   - Pass our own client as the reflection model if the library accepts a model object, so reflection calls go through our cache and cost log.
   - Save the best-on-val prompt and the full candidate history to `runs/<run_id>/`.
3. Cost logger and budget stop.
4. Final-eval script for chunk 5: for each arm's final prompt, generate on test and miniF2F (arm F: test only, through its API), then compute the judge score, truth score and memorization check. Output `runs/final/<arm>.jsonl.gz`.
5. Analysis script for chunk 6, written now so results can't shape it: everything in the analysis plan in `prereg.md`, plus the exploratory numbers (miniF2F transfer, format breakage, error-tag shifts) labeled exploratory. Output `results.json` and the two figures.
6. Pod scripts: `setup_pod.sh` (install vLLM, download both models, serve both on one H100 by splitting GPU memory between two vLLM processes, health check) and `run_job.sh` (tmux, logs, push results, stop the pod).
7. One live smoke call through Together using the same client code, so the pilot doesn't discover client bugs while the GPU is billing.

**Tests**, with a mock formalizer, mock judge and mock AXLE:

- a GEPA run stops at its metric-call budget
- the feedback text contains the Lean errors and the judge's reason
- GEPA code can't load test or miniF2F items (firewall test)
- a second identical run makes zero new calls (cache)
- the cost cap stops a run
- the bootstrap recovers an effect planted in fake data (the interval covers +10 and excludes 0) and covers 0 when nothing is planted
- the decision rule labels hand-made intervals correctly
- the analysis script runs end to end on fake data and produces `results.json` and both figures

**Done when:** all tests pass and a full dry run on mocks works end to end.

---

## Chunk 4: Pilot and freeze (GPU)

**Neel does first** (any time before this chunk, for example while chunks 1 to 3 run):

1. Write arm E's checklist prompt to `prompts/arm_E.txt` (about 30 minutes).
2. Fill in and date the predictions table in `prereg.md`.
3. Make a RunPod account, add about $40, add the laptop's SSH public key in RunPod's settings, and start one H100 80GB pod with at least 100 GB of disk. Create a fine-grained GitHub token with write access to this repo only and add it to `.env` as `GITHUB_TOKEN`. Claude copies `.env` to the pod.

**Run** (the pilot steps in `prereg.md`):

1. `setup_pod.sh`, then measure tokens per second for both models.
2. Both models with their seed prompts on 30 val items, Qwen3-8B with thinking both on and off. Record compile rate, extraction failures, output length, and time and cost per item.
3. The memorization check on those outputs.
4. The full truth score on 20 of those items (mixed across models), then the labeling page. Neel labels them blind. Compute agreement with the reference judge.
5. One short GEPA run on Qwen3-8B, about 150 metric calls. Confirm the loop works and the judge score moves. Measure time and cost per metric call and project the full study.
6. A decision table for Neel: for each open choice, a recommendation and the pilot numbers behind it. Choices: Qwen3-8B thinking mode, temperature and sample count, output length cap, optimization judge, reference judge, reflection model, arm F's model, GEPA budget (about 800). Recommended: no judge, reflection or arm F model from the Qwen family, and the reflection model and arm F from a different family than the reference judge.
7. The go/no-go table from `prereg.md`: Qwen3-8B truth-faithful rate between about 10% and 70%; judge agreement at least 16/20; exact matches under about 20%; projected total under $300.
8. Neel picks, then confirms or changes the 5-point threshold. Claude writes the final values into `config.yaml` and `prereg.md`, and Neel checks the diff. Commit, tag `prereg-frozen`, push, stop the pod.

**If any go check fails:** stop the pod, write it up in `LOG.md`, and end the session. Neel takes it to a project chat.

**Done when:** the go/no-go table is filled, every number matches the subagent's recomputation, the tag is pushed and the pod is stopped.

---

## Chunk 5: Full runs (GPU, overnight)

**Neel does first:** start the pod again (or a fresh H100 with the same settings), and make sure RunPod has about $40 and the API accounts have about $140 between them for the reflection model, judges and arm F. Together that is the chunk's $180 cap.

**Session 1, launch (evening):**

1. `setup_pod.sh`, then launch the six GEPA runs (2 models × seeds 0, 1, 2) in parallel inside tmux with the frozen config.
2. Watch the first few iterations, confirm they look healthy, log it, end the session.

From there the job runs on its own:

3. After all six runs finish, an automatic sanity check: all six completed, each within budget, every best prompt non-empty. If it fails, the job pushes its logs and stops the pod.
4. Final eval of every arm (A, B ×3, C, D ×3 and E on test and miniF2F; F on test only) with judge score, truth score and memorization check.
5. Push results, stop the pod.

**Session 2, check (morning), "Continue chunk 5":** check the invariants and log health checks only, no per-arm scores:

- every GEPA run stayed within its budget
- every arm has every test item, and every usable miniF2F item (except F)
- no duplicate ids
- judge-faithful never exceeds compiled, and truth-faithful never exceeds compiled
- counts of format failures, compile failures and outages per arm

**Done when:** all invariants hold and the subagent's counts match.

---

## Chunk 6: Hand-check and analysis

**Build the sample:** every item where a certificate and the reference judge disagree (up to 25, chosen at random if there are more), plus a random sample stratified by arm (A, B, C, D, with seeds pooled) to bring the total to about 100. Shuffle, hide arm and model, generate the labeling page.

**Neel labels** (5 to 7 hours, any number of sittings). He doesn't open results or GEPA prompts until he's done.

**Then:**

1. Run the frozen analysis script on all results plus `labels.csv`.
2. A fresh subagent recomputes every headline number from the raw files with its own code.
3. Log the results table, the Q1 to Q3 readings, and the judge's error rate.

**Done when:** point estimates and counts match exactly and bootstrap intervals agree within 0.5 points.

---

## Chunk 7: Writeup and publish

1. Read the six optimized prompts and list the rules GEPA wrote (exploratory).
2. One-page writeup: the three answers with intervals, the rules GEPA wrote, the error types that moved, limitations, and related work (FormaRL, ReForm, BetterTogether, Beyond Compilation). No em dashes.
3. The two figures from chunk 6.
4. Repo cleanup: a README with exact reproduction steps, all prompts, every raw output with judge and truth labels, Neel's hand labels, and the run log.
5. Email drafts for Axiom and Pramaana, each tied to one concrete finding. Drafts only.
6. Checks: a script compares every number in the writeup with `results.json`; an em dash scan; a secret scan of the whole git history.
7. Neel reads and approves. Only then does the repo go public.

**Done when:** all checks pass and Neel signs off.
