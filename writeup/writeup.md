# Does GEPA make Lean formalizers more faithful? A preregistered test

**Neel Dankar.** Draft, 2026-10-25. Code, raw outputs and hand labels are in this repository. `prereg.md` was frozen before any test output existed; deviations are logged in it.

## Question

Does GEPA prompt optimization make Lean 4 statements more faithful to the English theorem, for a general and a fine-tuned 8B model? And does the judge GEPA optimizes against overstate the gain?

## Setup

Qwen3-8B and ReForm-8B each ran with a seed prompt (arms A and C) and GEPA-optimized prompts (arms B and D, 3 seeds each). GEPA saw only 50 train and 70 validation items, scored by a compile check plus a cheap judge. On 247 ProofNet-Verified test items, a statement is faithful if it compiles and an AXLE-checked proof shows it equivalent to the reference, or else a separate reference judge accepts it. Differences use a paired item bootstrap (10,000 resamples, 95% intervals) with a 5-point threshold.

## Results

All three answers are **inconclusive**: every interval includes 0 and reaches past 5 points.

| Question | Points [95% interval] |
|---|---|
| Q1: truth gain from GEPA, Qwen3-8B | +2.8 [-0.4, 6.6] |
| Q2: ReForm-8B's gain minus Qwen3-8B's | -2.7 [-8.9, 3.2] |
| Q3: change in the judge's false-positive rate, Qwen3-8B | +10.4 [-1.9, 21.8] |
| Q3: same, ReForm-8B | -1.4 [-6.7, 4.1] |

Truth by arm (%): A 4.5, B 7.3, C 51.0, D 51.1, E 6.5, F 71.7. E is a hand-written checklist prompt on Qwen3-8B; F is Kimi-K3, a ceiling reference. The checklist prompt (E) did about as well as GEPA (B); no interval was preregistered for that comparison.

## Findings

1. **Qwen3-8B's gain is compiling, not meaning.** It splits into a compile part of +3.3 [1.1, 6.3] and a meaning part of -0.4 [-4.2, 3.5]. The compile rate rose from 11.7% to 20.4% through fewer syntax errors (21.1% to 14.2% of outputs), not fewer invented names (41.7% to 41.0%; exploratory, by first Lean error).
2. **ReForm-8B: no detectable gain.** The difference is 0.1 [-4.9, 5.1]. The upper end just passes 5, so by the frozen rule this is inconclusive, not "no meaningful effect".
3. **The reference judge agrees with the author's blind hand labels on 89 of 99 outputs.** It errs mostly toward "unfaithful" (8 against 2), so truth rates, if anything, understate faithfulness. With hand labels as truth, Q1 is +3.6 [-3.6, 10.9].
4. **What GEPA wrote (exploratory).**
   - The prompts grew from 30 or 19 words to between 561 and 4,632: compile rules, warnings, and worked statements of items GEPA saw.
   - Of 158 Mathlib-style names they mention, all 14 called nonexistent are absent from AXLE's Mathlib, but so are 4 of the 124 presented only as usable (for example `Complex.abs`).
   - Across GEPA's candidates, the judge scored ReForm-8B about 6.1 points above truth, with no growth: -0.09 [-0.27, 0.08] points per iteration (Qwen3-8B: -0.05 [-0.22, 0.11]). This fits steady leniency better than a gap GEPA widened.

## Limitations

- **Qwen3-8B near the floor:** 6.7% pilot truth against a go criterion of about 10%; the study went ahead with the reason recorded.
- **Deviations,** all dated in `prereg.md`: the reflection model (Kimi-K3) moved to OpenRouter, pinned to Together's serving, without the sampling `seed` (Deviation 2); a re-ask fixed before scores were seen filled 159 of 160 missing reference-judge verdicts (Deviation 4).
- **Label provenance.** The author recorded hand labels in a ChatGPT conversation, which formatted them into the export file; the transcript is in the repo.
- **One optimization judge,** so gaming results may be judge-specific.
- **Small samples.** One labeler, labeling by hand; one sample per item, wide intervals.
- **Seed outputs.** Saved seed-candidate outputs differ from what GEPA scored on up to 7 of 70 items.

## Related work

GEPA (Agrawal et al., 2025) evolves prompts by reflecting in natural language on its rollouts; ReForm (Chen et al., 2025) and FormaRL (Huang et al., 2025) train formalizers on Lean compile plus LLM consistency rewards, and BetterTogether (Soylu et al., 2024) finds prompt optimization and fine-tuning work better combined, a question close to Q2. Beyond Compilation (Zhang et al., 2026) finds that, across eight systems, the gap between compiling and passing its two-judge faithfulness check reaches 29.5 points; finding 1 makes a related point for gains.
