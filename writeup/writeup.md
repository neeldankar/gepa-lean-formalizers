# Does GEPA make Lean formalizers more faithful? A preregistered test

**Neel Dankar.** Draft, 2026-10-24. Code, prompts, every raw output, the hand labels and the run log are in this repository. The plan was frozen in `prereg.md` before any test output existed.

## Setup

**Task.** Translate an English theorem into a Lean 4 statement. Test set: 247 ProofNet-Verified items, one sample per item.

**Arms.** Two 8B models, each with its starting prompt (the seed) and with prompts optimized by GEPA:
- Qwen3-8B, a general model: arms A (seed) and B (GEPA, 3 seeds).
- ReForm-8B, a fine-tuned formalizer: arms C (seed) and D (GEPA, 3 seeds).

**Optimization.** GEPA saw only 50 train and 70 validation items. It scored candidates with a cheap optimization judge: 1 if the statement compiles and the judge calls it faithful.

**Truth score.** A statement that does not compile is unfaithful. A compiled statement is faithful if an AXLE-checked proof shows it equivalent to the verified reference; otherwise a separate reference judge decides.

**Decisions.** Paired bootstrap over items (10,000 resamples), 95% intervals and a 5-point threshold. Each answer is "effect", "no meaningful effect" or "inconclusive".

## Answers

All three are **inconclusive**: each interval includes 0 and also reaches past 5 points.

| Question | Estimate, points [95% interval] |
|---|---|
| Q1: truth gain from GEPA, Qwen3-8B (B minus A) | +2.8 [-0.4, 6.6] |
| Q2: ReForm-8B's gain minus Qwen3-8B's gain | -2.7 [-8.9, 3.2] |
| Q3: change in the judge's false-positive rate, Qwen3-8B | +10.4 [-1.9, 21.8] |
| Q3: same, ReForm-8B | -1.4 [-6.7, 4.1] |

**Qwen3-8B: the gain is compiling, not meaning.**
- Truth score went from 4.5% (A) to 7.3% (B).
- Split into parts, the compile part is +3.3 points [1.1, 6.3] and the meaning part is -0.4 [-4.2, 3.5].
- Compile rate went from 11.7% to 20.4%, while the faithful rate among compiled outputs went from 37.9% to 35.8%.
- The judge score rose more than the truth score, by 2.4 points [0.4, 4.9]. This gap is descriptive, with no decision rule.

**ReForm-8B: near zero.**
- Truth score was 51.0% (C) and 51.1% (D), a gain of 0.1 points [-4.9, 5.1].
- Compile rate stayed flat (67.2% and 66.4%).

**The reference judge against the author's labels.**
- The author labeled 101 compiled outputs blind (arm, model and scores hidden).
- On the random part of that sample, the reference judge agreed on 89 of 99 outputs. It called 2 unfaithful outputs faithful and 8 faithful outputs unfaithful.
- Agreement was lower on Qwen3-8B's outputs (A 4 of 7, B 13 of 16) than on ReForm-8B's (36 of 38 in each arm).
- With the hand labels as truth on that sample, every interval for Q1 to Q3 includes 0. For example, Q1 is +3.6 [-3.6, 10.9].

**What GEPA wrote (exploratory).**
- The optimized prompts grew from 30 words (Qwen3-8B's seed) to between 1,677 and 4,632 words, and from 19 words (ReForm-8B's seed) to between 561 and 2,432 words.
- All six spell out that a statement that fails to compile scores 0, and ask for every hypothesis to be kept.
- Most add lists of Mathlib names that do not exist and Lean 4 syntax traps.
- Four copy complete worked statements of problems GEPA saw during optimization.
- Details are in `writeup/gepa_rules.md`.

**Compile errors (exploratory).**
- Each Qwen3-8B test output that failed to compile was put in a bucket by its first Lean error.
- An unknown name (a Mathlib identifier or field that does not exist) was the first error in 41.7% of all outputs with the seed prompt and 41.0% after GEPA. So the optimized prompts' lists of nonexistent names did not lower this rate.
- Syntax errors fell from 21.1% to 14.2% of outputs.
- Details are in `runs/chunk7/compile_errors.json`.

**Judge vs truth during optimization (exploratory).** Every candidate prompt GEPA saved was given truth labels on the 70 validation items (`figures/exploratory_judge_vs_truth_iterations.png`).
- For ReForm-8B, the judge score was above the truth score for all 31 candidates.
- For Qwen3-8B, the judge score was above the truth score for 17 of 33 candidates and equal for 10.

## Limitations

- **Qwen3-8B sits near the floor.**
  - The preregistered go criterion asked for a truth rate of at least about 10% in the pilot. Qwen3-8B reached 6.7%, and the study went ahead with the reason recorded in the preregistration.
  - On the test set the seed arm scored 4.5%.
  - So the Qwen3-8B result says GEPA did not clearly lift a model near the floor. It does not say GEPA cannot help a stronger general model.
- **Kimi-K3 host move.** After outages on Together's API, the reflection model (Kimi-K3) was reached through OpenRouter, pinned to Together's serving, with the same model, temperatures and token limits. One request field, the sampling `seed`, could no longer be sent (Deviation 2).
- **Missing-verdict re-ask.**
  - In the final eval, 160 reference-judge verdicts were missing. A parser fix and a uniform re-ask, decided before any scores were seen, filled 159 of them; 1 remains missing, in the miniF2F transfer set (Deviation 4).
  - GEPA's own history was not changed: during optimization, 96 of 4,480 saved validation evaluations had an unreadable judge reply and were scored 0.
- **Label provenance.** The author recorded hand labels in a ChatGPT conversation, which formatted them into the export file; the transcript is in the repo.
- **One labeler, small sample, one sample per item.** The intervals are wide; Q2 especially is a difference of differences.

## Related work

- **GEPA** (Agrawal et al., 2025) evolves prompts by reflecting on its own trajectories. On its tasks it reports beating GRPO with far fewer rollouts. This study applies it to faithfulness, where the score it optimizes is a judge, not the truth.
- **ReForm** (Chen et al., 2025) trains a formalizer to check its own semantic consistency and correct itself. ReForm-8B is the specialist here.
- **FormaRL** (Huang et al., 2025) rewards a formalizer with a Lean compile check plus an LLM consistency check, using reinforcement learning with little labeled data.
- **BetterTogether** (Soylu et al., 2024) finds that prompt optimization and fine-tuning work best combined. Q2 asks the related question of whether prompts still add anything to a fine-tuned model.
- **Beyond Compilation** (Zhang et al., 2026) shows that compiling overstates faithfulness, by up to 29.5 points across eight systems. The compile-versus-meaning split here makes a related point for gains: most of Qwen3-8B's gain came from compiling more often.
