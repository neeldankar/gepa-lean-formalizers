# Draft prereg change: three analysis additions (not applied)

Drafted 2026-10-21 in chunk 4 at Neel's request (his cut-scope list, item 3). Neel edits and applies it, or doesn't. `src/analysis.py` already computes all three, with tests. None has a decision rule; all are reported alongside the confirmatory results.

## Analysis plan, "Reported alongside every truth-score result": add three bullets

After the existing bullet "compile rate and faithful-given-compiled, separately", add:

> - per arm, the share of truth labels that came from an equivalence certificate, from the reference judge, and from a compile failure (format failures counted as compile failures, and also shown on their own)
> - the reference judge's errors against Neel's hand labels on the random part of the hand-check sample, split into false positives (judge faithful, hand label unfaithful) and false negatives (judge unfaithful, hand label faithful), overall and per arm
> - each truth gain split into a compile part and a meaning part: Δtruth = f0·Δc + c1·Δf, where c is the compile rate and f is the faithful rate among compiled outputs, before (0) and after (1) GEPA. Reported for Q1 (A to B) and for both terms of Q2 (C to D, and A to B), each part with a 95% paired-bootstrap interval. For GEPA arms, c and f are pooled over the three seeds, so the two parts add up exactly to the truth gain.

## Changes: new item

Number it after the Q3 and few-shot drafts (16 if both go in as 14 and 15).

> **Three analysis additions, all reported alongside, none confirmatory.** Truth-label sources per arm; the reference judge's false positives and false negatives against the hand labels; and a split of each truth gain into a compile part and a meaning part (Analysis plan). Added before the freeze, before any test-set output exists.

## Notes for Neel (not prereg text)

- The split matters because the pilot's Qwen3-8B outputs mostly fail to compile (6 to 20% compile on the 30 pilot items). A GEPA gain there could be almost all compile part, and this split shows that directly.
- The compile part uses f0, the before-GEPA faithful rate among compiled outputs, and the meaning part uses c1, the after-GEPA compile rate. Using the other weighting (c0·Δf + f1·Δc) also adds up exactly but splits the gain differently. The draft fixes the weighting you gave.
