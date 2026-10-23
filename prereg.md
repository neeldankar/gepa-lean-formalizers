# GEPA on Lean Formalizers: Pre-registration

Neel Dankar · drafted Oct 17, 2026 from the design doc of the same date

**Status: FROZEN** on 2026-10-22, at the end of chunk 4, with the git tag `prereg-frozen`. It never changes after that; deviations go in the Deviations section at the bottom, dated and approved by Neel.

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
14. **Q3 is the judge's false-positive rate among compiled outputs.** For each arm, the false-positive rate is the number of compiled outputs the optimization judge calls faithful but the truth label calls unfaithful, divided by the number of compiled outputs. Q3 is that rate in the GEPA arm minus the seed arm, per model (B minus A, D minus C), with the paired bootstrap and the same decision rule as Q1 and Q2. Judge-score gain minus truth-score gain is still reported, as a descriptive number without a decision rule. A prompt that only raises the compile rate moves the judge score and the truth score together, and the false-positive rate is not affected by that.
15. **Arm A's seed prompt has three fixed train examples.**

    **The pilot.** Qwen3-8B with the one-line seed was truth-faithful on 2 of 30 pilot validation items, mostly because its outputs did not compile. Neel then added a block of Lean 4 syntax rules to the seed; that run was truth-faithful on 1 of 30, so the block was removed.

    **The examples.** The seed is now the original instruction line followed by a fixed few-shot block of three examples. Each example is laid out like a real query: the English statement, then that item's Lean context block (header and opens; none of the three has helper definitions), then the answer, its ProofNet-Verified reference statement ending in `:= by sorry`, in a ```lean4 block. The three are drawn with seed 0 from the 43 train items that have no helper definitions and whose reference compiles with `autoImplicit` off: pnv_218 (Dummit_Foote_exercise_1_3_8), pnv_226 (Dummit_Foote_exercise_3_2_16) and pnv_018 (Axler_exercise_4_4). No validation or test item is used.

    **Arms E and F.** Arm E (the checklist) and arm F (arm A's prompt on the frontier model) get the same block.

    **GEPA.** In arm B, GEPA optimizes only the instruction text. The examples are a fixed suffix that GEPA never sees or edits, so every GEPA candidate keeps the same three examples. The three example items are left out of GEPA's trainset, because their answers are in the prompt. Every GEPA run, arm B and arm D alike, trains on the other 47 train items, so the two models are optimized on the same items. The validation set (70 items) and the split file are unchanged.

    **Arms C and D** are unchanged: ReForm-8B's own prompt (Changes, item 11), with no examples.

    This is the last change to arm A before the freeze.
16. **Three analysis additions, all reported alongside, none confirmatory.** Truth-label sources per arm; the reference judge's false positives and false negatives against the hand labels; and a split of each truth gain into a compile part and a meaning part (Analysis plan). Added before the freeze, before any test-set output exists.
17. **A judge reply that stays unparseable is a missing verdict, never a verdict.** Both judges must reply with JSON holding a valid verdict. An unparseable reply is asked again once; if the second reply is also unparseable, the verdict is recorded as missing. A missing verdict counts neither as faithful nor as unfaithful: the item is left out of that arm's judge score (optimization judge) or truth score (reference judge, when no certificate settles the item), the paired bootstrap still resamples items, and missing counts are reported per arm and per judge. A certificate still settles the truth label without the reference judge. Inside GEPA, which needs a number for every example, a missing optimization-judge verdict scores 0 for that example and the feedback says the judge's reply could not be read. Neel, at the freeze (2026-10-22).

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
| Q3 | Do judge-measured gains overstate real gains? | For each model: the judge's false-positive rate among compiled outputs (judge faithful, truth unfaithful, divided by compiled), GEPA arm minus seed arm |

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
| General model | Qwen3-8B, thinking mode off in every arm (pilot; Neel, 2026-10-18) | Fixed (pilot) |
| Specialist | [ReForm-8B](https://huggingface.co/GuoxinChen/ReForm-8B): fine-tuned from Qwen3-8B-Base for formalization, Apache-2.0. Its example uses up to 32,768 new tokens, so outputs are long. The output length cap is 16,384 new tokens in every arm (pilot). | Fixed (pilot) |
| Lean checking | AXLE `check` in the `lean-4.28.0` environment, matching ProofNet-Verified | Fixed |
| Optimization judge | `openai/gpt-oss-120b` on Together: a cheap reference-free LLM judge from a different model family than the reference judge | Fixed (pilot) |
| Reference judge | `deepseek-ai/DeepSeek-V4.1-Flash` on Together (Scoring, layer 3). It agreed with Neel's labels on 19 of the 19 pilot items with a verdict (1 missing). | Fixed (pilot) |
| GEPA | The open-source `gepa` library (0.1.4) with a custom adapter, library defaults otherwise. Same metric-call budget per run (800), same reflection model (`moonshotai/Kimi-K3` on Together: not Qwen, not the reference judge's family), 3 seeds per arm. GEPA's score is 1 only if the output compiles and the judge says faithful. Its feedback text is Lean's errors plus the judge's verdict and reason. | Fixed (pilot) |
| Sampling | Temperature 0.6 and 1 sample per item in every arm (pilot) | Fixed (pilot) |

**Diagram: GEPA only sees the judge; the truth score is computed once, at the end.**

- *Optimization loop (train and validation sets):* current prompt (starts as the seed) → formalizer (Qwen3-8B or ReForm-8B) → Lean check (AXLE, comments stripped) → optimization judge (no reference answer) → GEPA reflection, which reads the score, the Lean errors and the judge's reason, and rewrites the prompt → new current prompt.
- *Evaluation, once at the end:* final prompts (best on validation) → formalizer on test + miniF2F, once → two scores: the judge score (same judge as in training) and the truth score, never seen by GEPA (compile check, equivalence certificate, reference-aware judge; Neel's hand-check measures the remaining error).

GEPA's loop only ever sees the cheap judge. At the end, every arm's final prompt (the seed, or GEPA's pick on validation) gets both scores, and Q3 asks whether GEPA's prompts make the judge call more wrong outputs faithful.

The test split and the miniF2F set are scored once, after all GEPA runs finish. Nothing about them feeds back into optimization.

## Scoring

The truth score is the weak point of the whole design, so it is built in layers. Each layer covers a different gap, and the hand-check measures how much error is left.

**Before any judge sees an output:**

- **Strip comments and docstrings, and rename the theorem to a fixed name.** Use AXLE's `remove_comments` if it passes our stripper tests, otherwise our own tested stripper (Changes, item 7); AXLE's `normalize` can turn docstrings into plain comments first. Without this, GEPA could learn to persuade judges with comments like `-- faithful translation`, and Q3 would measure prompt injection instead of meaning.
- **Extract the final Lean statement.** If none can be found, record a format failure. This matters most for ReForm-8B's long outputs.

**Judge score**, the score GEPA optimizes: 1 if the statement compiles (with `autoImplicit` off, Changes item 10) and the optimization judge, which sees only the English and the candidate, says faithful. Otherwise 0. A judge reply that is still unparseable after one re-ask is a missing verdict, not a 0 (Changes, item 17).

**Truth score**, used only for evaluation:

1. **Compile check**, with `autoImplicit` off (Changes, item 10). A failure counts as unfaithful, but compile rate is reported separately. That keeps Mathlib version drift (old lemma names) apart from meaning errors.
2. **Equivalence certificate.** Try to prove candidate → reference and reference → candidate in Lean with cheap automation through AXLE. Proving both directions settles the item as faithful. One trap: both statements are true theorems, so a direction can be "proved" from scratch without using the other statement. A direction only counts if it fails once its hypothesis is removed. Certificates only confirm faithfulness and never refute it, so a failed attempt means unknown.
3. **Reference-aware judge.** On every compiled item, a strong judge from a different model family than the optimization judge sees the English, the reference, and the candidate, and gives a verdict, a reason, and, for unfaithful items, an error tag from ProofNet-Verified's taxonomy.
4. **Truth label.** The certificate when there is one, otherwise the reference judge's verdict. If that verdict is missing, the truth label is missing (Changes, item 17).

**Neel's hand-check.** Neel labels about 100 test outputs from the four core arms, blind to arm and model: every item where a certificate and the reference judge disagree (up to 25, sampled at random if there are more), plus one set of randomly chosen test items labeled in all four core arms (for B and D, one GEPA seed chosen at random per item), enough items to bring the total to about 100 (Changes, item 13). Arm and model stay hidden and the page order is shuffled. The random part gives the reference judge's error rate, which is reported next to every truth-score result. The disagreement part checks the certificates and is reported separately. Hand labels never overwrite the primary truth score.

**If the certificate layer is dropped** (Changes, item 8), the truth label is the reference judge's verdict on every compiled item, and the hand-check sample is entirely random.

**Memorization check.** Normalize every test output (fixed theorem name, no comments, AXLE `normalize`) and count exact matches against ProofNet-Verified, ProofNet# and the original ProofNet statements (Lean 4 versions only), per arm. A high match rate gets reported and makes the miniF2F transfer result carry more weight.

## Arms

The four core arms form the 2×2. Two cheap reference points show where the numbers sit. Every GEPA run gets the same budget of metric calls: 800 (fixed in the pilot).

| Arm | Model | Prompt | GEPA seeds | Role |
| --- | --- | --- | --- | --- |
| A | Qwen3-8B | Seed prompt: one instruction line plus three fixed train examples (Changes, item 15) | none | Core: general model, before |
| B | Qwen3-8B | GEPA, starting from A's instruction line; the three examples are a fixed suffix GEPA can't edit | 3 | Core: general model, after |
| C | ReForm-8B | Its own prompt from its released code ("Think step by step to translate the mathematical problem in natural language to Lean 4, and verify the consistency." then the English statement; Changes, item 11) | none | Core: specialist, before |
| D | ReForm-8B | GEPA, starting from C's prompt | 3 | Core: specialist, after |
| E | Qwen3-8B | A careful hand-written checklist prompt: list every hypothesis, check number types, check quantifiers. Drafted by Claude from the task description and edited by Neel, before any GEPA output exists. Followed by arm A's three examples. | none | Does GEPA beat a person spending 30 minutes on a prompt? |
| F | One frontier model: `moonshotai/Kimi-K3` on Together | Arm A's seed prompt, with its three examples | none | Ceiling reference, test set only |

A vs B answers Q1. The gain in A to B compared with the gain in C to D answers Q2. The judge's false-positive rate within each pair answers Q3.

## Outcomes and predictions

Each confirmatory result has a pre-stated reading, so a null result is a finding rather than a failure.

| Result | Reading |
| --- | --- |
| B beats A and D beats C by similar amounts | Prompt optimization stacks on fine-tuning, a cheap extra layer for anyone with a fine-tuned formalizer |
| B beats A, D does not beat C | Fine-tuning already captures what prompts can teach |
| D is worse than C | Fine-tuned formalizers lose steerability; new instructions hurt them |
| B does not beat A | Prompt-level optimization doesn't make an 8B model more faithful on this task, and the rules GEPA wrote show why |
| The judge's false-positive rate rises after GEPA | GEPA learned to please the judge, a warning for anyone optimizing formalizers against judges |
| The judge's false-positive rate does not change after GEPA | Judge-guided prompt optimization is safe at this scale; RL with more freedom is the open risk |
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
- Q3: for each model, the judge's false-positive rate among compiled outputs, GEPA arm minus seed arm (B minus A, D minus C). For a GEPA arm, the rate is computed per seed as a ratio of sums over items and then averaged over the 3 seeds; each bootstrap resample recomputes the ratio.

Descriptive, with the same bootstrap and no decision rule: for each model, judge-score gain minus truth-score gain.

**What counts as a result.** Smallest effect worth caring about: 5 points (confirmed by Neel at the freeze, 2026-10-22).

- "Effect" if the interval excludes 0 and the estimate is at least 5 points in size, in either direction, with the sign reported.
- "No meaningful effect" if the whole interval sits within ±5.
- "Inconclusive" otherwise.

**Power, honestly.** With 247 paired items, Q1's interval will likely be several points wide. Q2 is a difference of differences, so its interval will be wider still. Expect Q2 to be inconclusive unless the gap between models is large, and say so in the writeup rather than reaching for significance.

**Reported alongside every truth-score result:**

- the reference judge's agreement with Neel's hand labels on the random part of the hand-check sample, overall and per arm
- compile rate and faithful-given-compiled, separately
- per arm, the share of truth labels that came from an equivalence certificate, from the reference judge, and from a compile failure (format failures counted as compile failures, and also shown on their own)
- the reference judge's errors against Neel's hand labels on the random part of the hand-check sample, split into false positives (judge faithful, hand label unfaithful) and false negatives (judge unfaithful, hand label faithful), overall and per arm
- each truth gain split into a compile part and a meaning part: Δtruth = f0·Δc + c1·Δf, where c is the compile rate and f is the faithful rate among compiled outputs, before (0) and after (1) GEPA. Reported for Q1 (A to B) and for both terms of Q2 (C to D, and A to B), each part with a 95% paired-bootstrap interval. For GEPA arms, c and f are pooled over the three seeds, so the two parts add up exactly to the truth gain.
- missing judge verdicts per arm, for each judge, and missing truth labels (Changes, item 17)
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

**Pilot result (2026-10-22).** Go criterion 1 is not met: with the final seed (arm A's instruction line plus the few-shot block), Qwen3-8B was truth-faithful on 6.7% of the 30 pilot validation items (2 of 30), below the roughly 10% floor. The earlier seeds gave 6.7% and 3.3%. The other three criteria are met: the reference judge agrees with Neel's labels on 19 of the 19 items with a verdict (1 of 20 missing), exact matches are 0% in every configuration, and the projected total is at most about $94.

We proceed because:

1. The criterion is there to leave room to move. At 6.7% there is plenty of room upward; the risk is only a floor effect for B minus A.
2. ReForm-8B is at 46.7% (14 of 30), inside the range, so D minus C is unaffected.
3. The main question, whether judge-measured gains overstate real ones (Q2, Q3), needs compiled outputs and judge verdicts, not a minimum faithful rate.
4. Switching the general model would break the shared Qwen3-8B-Base design that Q2 depends on.

Consequence: Qwen3-8B's results are read with the floor in mind. A null for B minus A says GEPA did not lift a model near the floor, not that it cannot help a stronger one.

The schedule and per-chunk budget caps are in `CHUNKS.md`.

## Budget

A rough estimate, to be replaced by pilot measurements: about $140 to $200 in total, under the $300 cap.

| Item | Estimate |
| --- | --- |
| GEPA reflection model, 6 runs at up to about $10 each | about $60 |
| Rented H100 for both formalizers, pilot and full runs (about 15 GPU hours at about $2 to $2.70 per hour) | $30 to $45 |
| Reference-aware judge on every compiled test and miniF2F output, all arms | $30 to $50 |
| Optimization judge calls during GEPA and the final evaluation | under $20 |
| Arm F, frontier model on the test set | about $25 (Kimi-K3 at the 16,384-token cap, 247 items; pilot projection) |
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

After the freeze, every change to the plan goes here with a date, a reason, and Neel's approval.

1. **2026-10-22 (UTC), chunk 5, approved by Neel that night:** reflection retries 1→4 with backoff, after Together 429/503s during chunk 5; no model, prompt or scoring change. Waits before each retry are about 30, 60, 120 and 240 s with ±20% jitter; on a 429, Together's Retry-After wins when it asks for longer (at most 600 s). Jitter and Retry-After apply to every API retry, which changes only timing (judges keep their 5 s base wait). The six GEPA runs were stopped about 25 minutes in and resumed from their saved GEPA state.
2. **2026-10-22 (UTC), chunk 5, approved by Neel: routing only.** Kimi-K3 (GEPA reflection and arm F) is reached through OpenRouter instead of Together's own API, pinned to Together as the only provider (fallbacks off, all request parameters required), for every remaining call: the five unfinished GEPA runs (B_s0, B_s1, B_s2, D_s1, D_s2) and arm F's final eval. Same model, same serving (Together), same temperatures (reflection 0.0, arm F 0.6) and max_tokens; no prompt, scoring or budget change. One request field is no longer sent: `seed`, which OpenRouter lists as unsupported for Together's Kimi-K3 (with all parameters required, sending it would get the call refused). Reason: from 06:12 to 08:44 UTC on Oct 22, Together's API failed 53 Kimi-K3 attempts (46 HTTP 503s, each after about 340 s, and 7 HTTP 429s), and five runs stopped. Moonshot's own serving was not used because it fixes kimi-k3 at temperature 1.0. Each call's serving provider, as OpenRouter reports it, is logged.
3. **2026-10-22 (UTC), chunk 5, approved by Neel:** arm F's final eval runs after every other arm is done and pushed. Arm F calls get the same 4 retries with backoff as reflection (about 30, 60, 120 and 240 s, ±20% jitter; the 1800 s limit per attempt is unchanged). An arm F call that still fails is recorded as missing for that item: it is left out of arm F's rates and reported as `missing_generation`, never as a format failure, a compile failure or a job-ending error. Reason: arm F is the only final-eval arm on an outside API, after the Kimi-K3 failures on Oct 22. No change to models, prompts, sampling or scoring.
4. **2026-10-23 (UTC), chunk 5, approved by Neel, decided before any scores were seen:** a one-time pass over the final-eval rows that fills missing judge verdicts, the same way in every arm. (a) Parser fix for both judges: the frozen parser cut each reply at the first `}`, so a reason quoting Lean set notation such as `{x : ℕ | 0 < x}` was never read. When that pass finds nothing, whole JSON objects are now decoded. Any reply the old parser read gives the same result, so only missing verdicts can change. The fix is applied to every stored missing reply and to every new reply. (b) Reference judge: each of the 160 rows still missing after the fix is re-asked up to 3 times, with the same model, prompt and temperature (0), on new sample indices 2 to 4, and with the token cap raised from 4,000 to 16,000. Reason: 144 of the 160 replies were empty, because the judge spent its whole 4,000-token cap reasoning, and missingness rose with candidate length and differed by arm. At temperature 0 a larger cap doesn't change any verdict that already finished under 4,000 tokens, so this is equivalent to having used 16,000 from the start. (c) Optimization judge: the same parser fix on final-eval rows, and its rows still missing after that (malformed JSON) are re-asked up to 3 times with its original settings (4,000 tokens, temperature 0). (d) Truth labels of affected rows are recomputed under the frozen rule (certificate first, then the reference judge). (e) Cost goes to chunk 5. **Limitation:** GEPA's training history is unchanged. The same parser bug made some optimization-judge verdicts missing during the GEPA runs, and GEPA scored those as 0: 96 of 4,480 saved full-validation evaluations (B 17, D 79), all of which the fixed parser reads (`runs/chunk5_deviation4.json`).
