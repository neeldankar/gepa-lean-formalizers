# Does GEPA make Lean formalizers more faithful? A preregistered test

**Neel Dankar.** Draft, 2026-10-25. Code, prompts, raw outputs and hand labels are in this repository; `prereg.md` was frozen before any test output existed.

## Question

Does GEPA prompt optimization make Lean 4 statements more faithful to the English theorem, for a general and a fine-tuned 8B model? And does the judge GEPA optimizes against overstate the gain?

## Setup

Qwen3-8B (general) and ReForm-8B (fine-tuned formalizer) each ran with a seed prompt (arms A and C) and with GEPA-optimized prompts (arms B and D, 3 seeds each). GEPA saw only 50 train and 70 validation items, scored by a compile check plus a cheap judge. On 247 ProofNet-Verified test items, a statement is faithful if it compiles and an AXLE-checked proof shows it equivalent to the reference or, failing that, a separate reference judge accepts it. Differences use a paired bootstrap over items (10,000 resamples, 95% intervals) with a 5-point threshold.

## Results

All three answers are **inconclusive**: every interval includes 0 and reaches past 5 points.

| Question | Points [95% interval] |
|---|---|
| Q1: truth gain from GEPA, Qwen3-8B | +2.8 [-0.4, 6.6] |
| Q2: ReForm-8B's gain minus Qwen3-8B's | -2.7 [-8.9, 3.2] |
| Q3: change in the judge's false-positive rate, Qwen3-8B | +10.4 [-1.9, 21.8] |
| Q3: same, ReForm-8B | -1.4 [-6.7, 4.1] |

## Findings

1. **Qwen3-8B's gain is compiling, not meaning.** Truth went from 4.5% to 7.3%: a compile part of +3.3 [1.1, 6.3] and a meaning part of -0.4 [-4.2, 3.5]. The compile rate rose from 11.7% to 20.4%; the faithful share among compiled outputs went from 37.9% to 35.8%.
2. **ReForm-8B: no gain.** Truth was 51.0% (seed) and 51.1% (GEPA), a difference of 0.1 [-4.9, 5.1].
3. **The reference judge mostly agrees with the author's blind labels:** 89 of 99 outputs, with 2 false positives and 8 false negatives. With the hand labels as truth, Q1 is +3.6 [-3.6, 10.9].
4. **What GEPA wrote (exploratory).**
   - The prompts grew from 30 or 19 words to between 561 and 4,632: mostly compile rules, warnings and worked statements of items GEPA saw.
   - They mention 158 distinct Mathlib-style names. All 14 they call nonexistent are absent from AXLE's Mathlib, but so are 4 of the 124 they present only as usable (for example `Complex.abs`).
   - An unknown name was the first compile error in 41.7% of Qwen3-8B outputs with the seed prompt and 41.0% after GEPA.
   - Across GEPA's saved candidates, the judge scored ReForm-8B about 6.1 points above truth, but the gap did not grow over iterations: -0.09 [-0.27, 0.08] points per iteration (Qwen3-8B: -0.05 [-0.22, 0.11]). This fits steady judge leniency better than a gap GEPA widened.

## Limitations

- **Qwen3-8B near the floor.** The go criterion asked for about 10% pilot truth; Qwen3-8B reached 6.7%, and the study went ahead with the reason recorded.
- **Kimi-K3 host move.** The reflection model moved to OpenRouter, pinned to Together's serving, without the sampling `seed` (Deviation 2).
- **Missing-verdict re-ask.** A uniform re-ask, decided before scores were seen, filled 159 of 160 missing reference-judge verdicts (Deviation 4).
- **Label provenance.** The author recorded hand labels in a ChatGPT conversation, which formatted them into the export file; the transcript is in the repo.
- **Small samples.** One labeler, one sample per item, wide intervals.
- **Seed outputs.** The seed candidate's saved outputs differ from what GEPA scored on up to 7 of 70 items.

## Related work

GEPA (Agrawal et al., 2025) evolves prompts by reflection, while ReForm (Chen et al., 2025) and FormaRL (Huang et al., 2025) train formalizers with consistency and compile rewards, and BetterTogether (Soylu et al., 2024) combines prompt optimization with fine-tuning, which Q2 tests. Beyond Compilation (Zhang et al., 2026) shows that compiling overstates faithfulness by up to 29.5 points; finding 1 makes the same point for gains.
