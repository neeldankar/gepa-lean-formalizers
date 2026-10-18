# GEPA on Lean Formalizers: Pre-registration

Neel Dankar · drafted Oct 17, 2026 from the design doc of the same date

**Status: DRAFT.** Frozen at the end of chunk 4 with the git tag `prereg-frozen`. Before then, only Neel edits this file. After that it never changes; deviations go in the Deviations section at the bottom, dated and approved by Neel.

This file is the spec. If it differs from the design doc saved in the claude.ai project or the live Claude Doc, this file wins.

## Changes from the Oct 17 design doc

1. **Hosting is decided.** Both formalizers run on one rented H100 (RunPod) with vLLM, so they share one server and identical sampling code. Qwen3-8B moves off Together; Together still serves the judges. Featherless is dropped: its cheaper plans allow 2 to 4 concurrent requests with 16K to 32K context, too tight for ReForm-8B's long outputs, and it serves models in FP8.
2. **The reference-aware judge runs on every compiled item**, not only on items without a certificate. Otherwise certificate vs judge disagreements could never occur, yet the hand-check samples them. The truth label still comes from the certificate when there is one.
3. **The judge's error rate comes from the random part of the hand-check sample only.** The disagreement part checks the certificates, is reported separately, and is capped at 25 items. Hand labels never overwrite the primary truth score.
4. **The labeling page glosses each Lean statement on its own** and never compares them, so Neel's labels can't anchor on the judge.
5. **Error-type tags come from the reference judge**, in the same call as its verdict.
6. **Arm E's prompt and Neel's predictions are written before the pilot's short GEPA run**, so neither can be shaped by GEPA output.
7. **Comment stripping.** The AXLE Python package does ship a `remove_comments` helper, though the web docs don't list it. We use it only if it passes our stripper tests (line, nested block and doc comments, and `--` inside string literals); otherwise we use our own tested stripper. AXLE's `normalize` can turn docstrings into plain comments first.
8. **Contingencies.** If the equivalence certificate layer can't pass its golden test cases by the end of chunk 2, it is dropped before the pilot, and the truth label becomes the reference judge's verdict on every compiled item, checked by the hand-check. miniF2F items that don't compile in `lean-4.28.0` are dropped and counted, never hand-fixed. Before compiling, miniF2F items get one scripted, syntax-only rewrite: the old big-operator binder `∑ x in s` (and `∏`) becomes `∑ x ∈ s`. Items that still don't compile are dropped and counted. There are no other edits, and nothing is fixed by hand.
9. **No existing GEPA pipeline.** GEPA comes from the open-source `gepa` library, pinned to version 0.1.4, through a small custom adapter built in chunk 3. Everything not set here uses the library's defaults (Pareto candidate selection, reflection minibatches of 3, no merging). The reflection model becomes a pilot decision.
10. **autoImplicit is off for candidates.** AXLE's Lean environment has `autoImplicit` on, so an unknown name in a model output silently becomes a bound variable and the statement still compiles. Every candidate is compiled as `set_option autoImplicit false in` followed by the theorem, in the judge score, the truth score and the certificates. References are compiled as ProofNet-Verified ships them.
11. **Arm C uses ReForm-8B's own prompt** from its released code: `Think step by step to translate the mathematical problem in natural language to Lean 4, and verify the consistency.` followed by a newline, the English statement and a newline, sent as one user message through the model's chat template (github.com/Chen-GX/ReForm, `lean_plugins/generate.py` line 38, commit `0047fdf`). This replaces the shorter sentence quoted from the model card. A seed weaker than the prompt ReForm-8B was trained with would inflate D minus C. Every arm's user message then adds the same fixed block with the item's Lean header and helper definitions (Setup, Task).
12. **Faithful means logically equivalent.** A candidate with an equivalence certificate counts as faithful even if it adds always-true clauses, since it states the same proposition as the reference. Items where a certificate and the reference judge disagree go to the hand-check, and their count is reported.
13. **The random part of the hand-check is paired across arms.** One set of randomly chosen test items is labeled in all four core arms (for B and D, one GEPA seed chosen at random per item), enough items to bring the hand-check to about 100 labels in total. Q1 to Q3 on this subset use the paired bootstrap. The disagreement part (up to 25 items) is unchanged. Arm and model stay hidden and the page order is shuffled.

## Summary

This study tests whether GEPA prompt optimization makes Lean formalizers more faithful, whether it adds anything on top of fine-tuning, and whether judge-measured gains are real.

A formalizer turns an English math statement into a Lean 4 statement. We optimize two formalizers that share a base model: Qwen3-8B (general purpose) and ReForm-8B (fine-tuned for formalization, built on Qwen3-8B-Base). Each gets a seed prompt and a GEPA-optimized prompt, a 2×2 design.

Every output gets two scores:

- **Judge score:** a cheap LLM judge that never sees a reference answer. GEPA optimizes against this, the way formalizers are tuned in practice.
- **Truth score:** agreement with ProofNet-Verified's proven reference formalizations. GEPA never sees it.

Every outcome is informative, which is the point:

- If GEPA helps both models, prompt optimization stacks on fine-tuning.
- If it helps only the general model, fine-tuning already captures what prompts teach.
- If the judge score rises faster than the truth score, judge-guided optimization inflates results.

Axiom and Pramaana both build formalizers and both rely on judges, so each finding bears on how they tune theirs.

## Questions

Three questions are confirmatory, frozen before any full GEPA run. Everything else is labeled exploratory.

| # | Question | Measured as |
| --- | --- | --- |
| Q1 | Does GEPA make the general model more faithful? | Truth score, Qwen3-8B: GEPA prompt minus seed prompt |
| Q2 | Does GEPA add less to the fine-tuned specialist? | GEPA gain for ReForm-8B minus GEPA gain for Qwen3-8B, both on truth score |
| Q3 | Do judge-measured gains overstate real gains? | For each model: judge-score gain minus truth-score gain |

Exploratory analyses:

1. **What GEPA learned.** Read the optimized prompts and list the rules GEPA wrote, for example "use ℤ when the text says integer."
2. **Which errors moved.** Tag wrong outputs with ProofNet-Verified's own error taxonomy (missing premise, missing implicit premise, misunderstanding of Mathlib, and so on), before and after GEPA. The reference judge assigns the tag in the same call as its verdict.
3. **Transfer.** Score the final prompts on a second test set (miniF2F) to see whether gains carry outside ProofNet.
4. **Format breakage.** Track whether new prompts break ReForm-8B's trained output format.

## Setup

Both models share Qwen3-8B-Base, so the general vs specialist comparison isn't also a comparison of base models.

| Component | Choice | Status |
| --- | --- | --- |
| Task | Given an English statement plus ProofNet-Verified's header (imports, opens) and any helper definitions, write one Lean 4 theorem statement ending in `:= by sorry` | Fixed |
| Main data | [ProofNet-Verified](https://github.com/marcusm117/ProofNet-Verified): 367 undergraduate statements, each with an English statement and a reference formalization that has a formal proof. Lean 4.28.0, Apache-2.0. | Fixed |
| Splits | Seeded split stratified by textbook: 50 train (GEPA feedback), 70 validation (GEPA selection), 247 test, touched once at the end | Chunk 1 |
| Secondary test | miniF2F, AI-MO fixed version (244 statements), for the transfer check. Only items whose English statement and reference load and compile in `lean-4.28.0` after the one scripted binder rewrite (Changes, item 8) are used; the rest are dropped and counted. | Chunk 1 |
| Hosting | One rented H100 80GB (RunPod) running vLLM serves both formalizers with the same sampling code. Judges, the reflection model and arm F run through APIs. | Fixed |
| General model | Qwen3-8B. Thinking mode on or off is set in the pilot and then fixed for every arm. | Decide in pilot |
| Specialist | [ReForm-8B](https://huggingface.co/GuoxinChen/ReForm-8B): fine-tuned from Qwen3-8B-Base for formalization, Apache-2.0. Its example uses up to 32,768 new tokens, so outputs are long. The output length cap is set in the pilot and applies to every arm. | Decide cap in pilot |
| Lean checking | AXLE `check` in the `lean-4.28.0` environment, matching ProofNet-Verified | Fixed |
| Optimization judge | A cheap reference-free LLM judge from a different model family than the truth judge | Decide in pilot |
| GEPA | The open-source `gepa` library (0.1.4) with a custom adapter, library defaults otherwise. Same metric-call budget per run, same reflection model, 3 seeds per arm. GEPA's score is 1 only if the output compiles and the judge says faithful. Its feedback text is Lean's errors plus the judge's verdict and reason. | Fixed; reflection model decided in pilot |
| Sampling | Same temperature and sample count in every arm, set in the pilot | Decide in pilot |

**Diagram: GEPA only sees the judge; the truth score is computed once, at the end.**

- *Optimization loop (train and validation sets):* current prompt (starts as the seed) → formalizer (Qwen3-8B or ReForm-8B) → Lean check (AXLE, comments stripped) → optimization judge (no reference answer) → GEPA reflection, which reads the score, the Lean errors and the judge's reason, and rewrites the prompt → new current prompt.
- *Evaluation, once at the end:* final prompts (best on validation) → formalizer on test + miniF2F, once → two scores: the judge score (same judge as in training) and the truth score, never seen by GEPA (compile check, equivalence certificate, reference-aware judge; Neel's hand-check measures the remaining error).

GEPA's loop only ever sees the cheap judge. At the end, every arm's final prompt (the seed, or GEPA's pick on validation) gets both scores, and Q3 compares GEPA's gain on the judge score with its gain on the truth score.

The test split and the miniF2F set are scored once, after all GEPA runs finish. Nothing about them feeds back into optimization.

## Scoring

The truth score is the weak point of the whole design, so it is built in layers. Each layer covers a different gap, and the hand-check measures how much error is left.

**Before any judge sees an output:**

- **Strip comments and docstrings, and rename the theorem to a fixed name.** Use AXLE's `remove_comments` if it passes our stripper tests, otherwise our own tested stripper (Changes, item 7); AXLE's `normalize` can turn docstrings into plain comments first. Without this, GEPA could learn to persuade judges with comments like `-- faithful translation`, and Q3 would measure prompt injection instead of meaning.
- **Extract the final Lean statement.** If none can be found, record a format failure. This matters most for ReForm-8B's long outputs.

**Judge score**, the score GEPA optimizes: 1 if the statement compiles (with `autoImplicit` off, Changes item 10) and the optimization judge, which sees only the English and the candidate, says faithful. Otherwise 0.

**Truth score**, used only for evaluation:

1. **Compile check**, with `autoImplicit` off (Changes, item 10). A failure counts as unfaithful, but compile rate is reported separately. That keeps Mathlib version drift (old lemma names) apart from meaning errors.
2. **Equivalence certificate.** Try to prove candidate → reference and reference → candidate in Lean with cheap automation through AXLE. Proving both directions settles the item as faithful. One trap: both statements are true theorems, so a direction can be "proved" from scratch without using the other statement. A direction only counts if it fails once its hypothesis is removed. Certificates only confirm faithfulness and never refute it, so a failed attempt means unknown.
3. **Reference-aware judge.** On every compiled item, a strong judge from a different model family than the optimization judge sees the English, the reference, and the candidate, and gives a verdict, a reason, and, for unfaithful items, an error tag from ProofNet-Verified's taxonomy.
4. **Truth label.** The certificate when there is one, otherwise the reference judge's verdict.

**Neel's hand-check.** Neel labels about 100 test outputs from the four core arms, blind to arm and model: every item where a certificate and the reference judge disagree (up to 25, sampled at random if there are more), plus one set of randomly chosen test items labeled in all four core arms (for B and D, one GEPA seed chosen at random per item), enough items to bring the total to about 100 (Changes, item 13). Arm and model stay hidden and the page order is shuffled. The random part gives the reference judge's error rate, which is reported next to every truth-score result. The disagreement part checks the certificates and is reported separately. Hand labels never overwrite the primary truth score.

**If the certificate layer is dropped** (Changes, item 8), the truth label is the reference judge's verdict on every compiled item, and the hand-check sample is entirely random.

**Memorization check.** Normalize every test output (fixed theorem name, no comments, AXLE `normalize`) and count exact matches against ProofNet-Verified, ProofNet# and the original ProofNet statements (Lean 4 versions only), per arm. A high match rate gets reported and makes the miniF2F transfer result carry more weight.

## Arms

The four core arms form the 2×2. Two cheap reference points show where the numbers sit. Every GEPA run gets the same budget of metric calls, set in the pilot, roughly 800.

| Arm | Model | Prompt | GEPA seeds | Role |
| --- | --- | --- | --- | --- |
| A | Qwen3-8B | Plain seed prompt | none | Core: general model, before |
| B | Qwen3-8B | GEPA, starting from A's prompt | 3 | Core: general model, after |
| C | ReForm-8B | Its own prompt from its released code ("Think step by step to translate the mathematical problem in natural language to Lean 4, and verify the consistency." then the English statement; Changes, item 11) | none | Core: specialist, before |
| D | ReForm-8B | GEPA, starting from C's prompt | 3 | Core: specialist, after |
| E | Qwen3-8B | A careful hand-written checklist prompt: list every hypothesis, check number types, check quantifiers. Drafted by Claude from the task description and edited by Neel, before any GEPA output exists. | none | Does GEPA beat a person spending 30 minutes on a prompt? |
| F | One frontier model | Plain seed prompt | none | Ceiling reference, test set only |

A vs B answers Q1. The gain in A to B compared with the gain in C to D answers Q2. Judge score vs truth score within each pair answers Q3.

## Outcomes and predictions

Each confirmatory result has a pre-stated reading, so a null result is a finding rather than a failure.

| Result | Reading |
| --- | --- |
| B beats A and D beats C by similar amounts | Prompt optimization stacks on fine-tuning, a cheap extra layer for anyone with a fine-tuned formalizer |
| B beats A, D does not beat C | Fine-tuning already captures what prompts can teach |
| D is worse than C | Fine-tuned formalizers lose steerability; new instructions hurt them |
| B does not beat A | Prompt-level optimization doesn't make an 8B model more faithful on this task, and the rules GEPA wrote show why |
| Judge gain clearly larger than truth gain | GEPA learned to please the judge, a warning for anyone optimizing formalizers against judges |
| Judge gain and truth gain about equal | Judge-guided prompt optimization is safe at this scale; RL with more freedom is the open risk |
| E matches or beats B | A careful human prompt does as well as GEPA here |

**Neel's predictions.** Fill these in and date them before the pilot's short GEPA run.

| Question | Prediction | Confidence (%) | Date written |
| --- | --- | --- | --- |
| Q1: truth gain, Qwen3-8B (A to B), in points | +8 points | 50 | 2026-10-18 |
| Q2: truth gain, ReForm-8B (C to D), in points | +0 points | 70 | 2026-10-18 |
| Q3 (descriptive gap): judge gain minus truth gain, per model | Qwen3-8B +4 points, ReForm-8B +2 points | 40 | 2026-10-18 |
| Q3 (confirmatory): judge false-positive rate change, B minus A and D minus C, in points | Qwen3-8B +0 points, ReForm-8B +2 points | 50 | 2026-10-18 |
| Which error type GEPA fixes most | Missing premise | 50 | 2026-10-18 |
| Does GEPA break ReForm-8B's format? | No | 60 | 2026-10-18 |

Confidence: for number rows, how sure I am the true value is within ±5 points of my prediction; for the other rows, how sure I am the prediction is right.

## Analysis plan

Neel checks and changes this before the freeze. Everything below is computed on the 247-item test split.

**Primary metric:** truth-scored faithful rate per arm. For GEPA arms, report each seed and the mean of 3.

**Confirmatory contrasts**, each with a 95% interval from a paired bootstrap that resamples test items (10,000 resamples), and seeds within GEPA arms:

- Q1: B minus A
- Q2: (D minus C) minus (B minus A)
- Q3: for each model, judge-score gain minus truth-score gain

**What counts as a result.** Proposed smallest effect worth caring about: 5 points.

- "Effect" if the interval excludes 0 and the estimate is at least 5 points in size, in either direction, with the sign reported.
- "No meaningful effect" if the whole interval sits within ±5.
- "Inconclusive" otherwise.

The 5-point threshold is a placeholder for Neel to confirm at the freeze.

**Power, honestly.** With 247 paired items, Q1's interval will likely be several points wide. Q2 is a difference of differences, so its interval will be wider still. Expect Q2 to be inconclusive unless the gap between models is large, and say so in the writeup rather than reaching for significance.

**Reported alongside every truth-score result:**

- the reference judge's agreement with Neel's hand labels on the random part of the hand-check sample, overall and per arm
- compile rate and faithful-given-compiled, separately
- the memorization rate per arm, plus Q1 to Q3 recomputed without exact matches
- Q1 to Q3 recomputed on the random part of the hand-labeled sample only, with the paired bootstrap over its items (Changes, item 13), as a sensitivity check
- the number of items where a certificate and the reference judge disagree, per arm (Changes, item 12)

Exploratory analyses are labeled exploratory. Every run, including broken or discarded ones, goes in the run log (`LOG.md`).

## Risks and fixes

The first four risks decide whether the results can be trusted, so the pilot tests them directly.

| Risk | Fix | When |
| --- | --- | --- |
| Truth score is noisy, because correct formalizations can look different | Layered truth score: compile check, equivalence certificates, a reference-aware judge on every compiled item, and a hand-check that measures the remaining error | Pilot on 20 items, then the full run |
| Hand-checking Lean is slow and the notation is new | Side-by-side view of English, reference and candidate, each Lean statement glossed on its own in plain English (never compared, no verdict); unsure items flagged rather than guessed; about a day budgeted; labels blind to arm | Throughout |
| Models recall ProofNet's answers | Exact-match rate after normalizing, Q1 to Q3 recomputed without matches, miniF2F transfer set | Pilot, then the full run |
| Specialist confounds | Base model confirmed shared (both from Qwen3-8B-Base). Both served by the same vLLM setup. Compile failures, which include version drift, reported apart from meaning errors. Format breakage logged as a finding. Output length capped and measured. | Pilot |
| Equivalence certificates can be faked by proving a true statement from scratch | A direction only counts if it fails once its hypothesis is removed | Built in |
| Certificate layer may not work in time | 3-hour timebox in chunk 2; if it fails, it is dropped before the pilot (Changes, item 8) | Chunk 2 |
| GEPA learns to persuade the judge with comments | Comments stripped and the theorem renamed before any judge sees the output | Built in |
| Small test set | 247 test items, intervals on every number, a smallest effect fixed in advance, and Q2's low power stated up front | Analysis |
| Gaming depends on which judge is optimized against | Say so plainly; add a second optimization judge only if budget remains | Writeup |
| Gains are small | Every outcome has a reading, and the rules GEPA wrote are analyzed either way | Writeup |
| Novelty is moderate | Position against FormaRL, ReForm and BetterTogether; claim only the specific contributions | Writeup |
| Hosting | Both models on one rented H100 with vLLM; Qwen3-8B's thinking mode set explicitly through its chat template; both tested end to end | Pilot |

## Pilot and go criteria

The pilot (chunk 4) tests the risky parts on small slices before real money is spent.

**Pilot steps:**

1. (Done in chunk 1) Load ProofNet-Verified, confirm all 367 references compile in AXLE's `lean-4.28.0` environment, and make the seeded split.
2. Run both models with their seed prompts on 30 validation items, Qwen3-8B with thinking on and off. Record compile rate, extraction failures, output length, and time and cost per item.
3. Run the memorization check on those outputs.
4. Run the full truth-score pipeline on 20 items, hand-label them blind, and measure agreement.
5. With arm E's prompt and Neel's predictions already committed, do one short GEPA run on Qwen3-8B, about 150 metric calls, to confirm the loop works and the judge score moves.
6. Fix the open choices (thinking mode, sampling, output cap, both judges, the reflection model, arm F's model, GEPA budget), confirm the threshold, and tag the frozen plan before any full run.

**Go if all of these hold:**

- Qwen3-8B's truth-scored faithful rate on the pilot items is between roughly 10% and 70%, leaving room to move either way.
- The reference judge agrees with Neel's labels on at least 16 of 20 items.
- Exact matches with known ProofNet statements are under about 20%. Above that, the miniF2F transfer set becomes the headline.
- Measured cost per GEPA run puts the whole study under $300.

The schedule and per-chunk budget caps are in `CHUNKS.md`.

## Budget

A rough estimate, to be replaced by pilot measurements: about $140 to $200 in total, under the $300 cap.

| Item | Estimate |
| --- | --- |
| GEPA reflection model, 6 runs at up to about $10 each | about $60 |
| Rented H100 for both formalizers, pilot and full runs (about 15 GPU hours at about $2 to $2.70 per hour) | $30 to $45 |
| Reference-aware judge on every compiled test and miniF2F output, all arms | $30 to $50 |
| Optimization judge calls during GEPA and the final evaluation | under $20 |
| Arm F, frontier model on the test set | under $10 |
| Development and pilot API calls (chunks 2 to 4) | about $15 |
| AXLE | free |

## Deliverables

Nothing goes public without Neel's sign-off.

1. **Frozen plan:** this file's questions, arms, scoring and analysis, plus Neel's dated predictions, committed and tagged before the first full run.
2. **Public repo:**
   - the formalization and scoring pipeline
   - all prompts, including every GEPA-optimized prompt
   - every raw output, with judge and truth labels
   - Neel's hand labels
   - the run log, including failed runs
   - a README with exact reproduction steps

   No API keys anywhere, including git history.
3. **One-page writeup:** the three answers with intervals, the rules GEPA wrote, the error types that moved, limitations, and related work (FormaRL, ReForm, BetterTogether, Beyond Compilation). No em dashes.
4. **Two figures:** truth score by arm with intervals, and judge gain vs truth gain per model.
5. **Email drafts** for Axiom and Pramaana, each tied to one concrete finding. Drafts only.

## Sources

- Data and models: [ProofNet-Verified](https://github.com/marcusm117/ProofNet-Verified) · [miniF2F, AI-MO version](https://huggingface.co/datasets/AI-MO/minif2f_test) · [ReForm-8B model card](https://huggingface.co/GuoxinChen/ReForm-8B)
- Tools: [AXLE docs](https://axle.axiommath.ai/v1/docs/) · [AXLE check](https://axle.axiommath.ai/v1/docs/tools/check/) · [AXLE normalize](https://axle.axiommath.ai/v1/docs/tools/normalize/) · [AXLE verify_proof](https://axle.axiommath.ai/v1/docs/tools/verify_proof/)
- Related work: [GEPA (2507.19457)](https://arxiv.org/abs/2507.19457) · [ReForm (2510.24592)](https://arxiv.org/abs/2510.24592) · [FormaRL (2508.18914)](https://arxiv.org/abs/2508.18914) · [BetterTogether (2407.10930)](https://arxiv.org/abs/2407.10930) · [Beyond Compilation (2606.31002)](https://arxiv.org/abs/2606.31002) · [Learning, Fast and Slow (2605.12484)](https://arxiv.org/abs/2605.12484), the source for reflection cost per run
- Equivalence checking: [BEq, ICLR 2025](https://proceedings.iclr.cc/paper_files/paper/2025/file/d630537fc4402cfa3ebbc7450a0cac91-Paper-Conference.pdf) · [BEq+ and ProofNetVerif (2406.07222)](https://arxiv.org/abs/2406.07222)

## Deviations

None yet. After the freeze, every change to the plan goes here with a date, a reason, and Neel's approval.
