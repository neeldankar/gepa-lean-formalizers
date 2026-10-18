# Draft prereg change: Q3 becomes the judge false-positive rate (not applied)

Drafted 2026-10-18 in chunk 4 at Neel's request. Neel edits and applies it, or doesn't. `src/analysis.py` already computes this measure (Q3) and keeps the old gap as descriptive.

## Changes, new item 14

> 14. **Q3 is the judge's false-positive rate among compiled outputs.** For each arm, the false-positive rate is the number of compiled outputs the optimization judge calls faithful but the truth label calls unfaithful, divided by the number of compiled outputs. Q3 is that rate in the GEPA arm minus the seed arm, per model (B minus A, D minus C), with the paired bootstrap and the same decision rule as Q1 and Q2. Judge-score gain minus truth-score gain is still reported, as a descriptive number without a decision rule. A prompt that only raises the compile rate moves the judge score and the truth score together, and the false-positive rate is not affected by that.

(The last sentence is my wording for the reason. Replace it with your own if you prefer.)

## Questions table (line 52)

Old:
> | Q3 | Do judge-measured gains overstate real gains? | For each model: judge-score gain minus truth-score gain |

New:
> | Q3 | Do judge-measured gains overstate real gains? | For each model: the judge's false-positive rate among compiled outputs (judge faithful, truth unfaithful, divided by compiled), GEPA arm minus seed arm |

## Setup, after the diagram (line 84)

Old:
> ... gets both scores, and Q3 compares GEPA's gain on the judge score with its gain on the truth score.

New:
> ... gets both scores, and Q3 asks whether GEPA's prompts make the judge call more wrong outputs faithful.

## Arms (line 125)

Old:
> Judge score vs truth score within each pair answers Q3.

New:
> The judge's false-positive rate within each pair answers Q3.

## Outcomes table (lines 137 and 138)

Old:
> | Judge gain clearly larger than truth gain | GEPA learned to please the judge, a warning for anyone optimizing formalizers against judges |
> | Judge gain and truth gain about equal | Judge-guided prompt optimization is safe at this scale; RL with more freedom is the open risk |

New:
> | The judge's false-positive rate rises after GEPA | GEPA learned to please the judge, a warning for anyone optimizing formalizers against judges |
> | The judge's false-positive rate does not change after GEPA | Judge-guided prompt optimization is safe at this scale; RL with more freedom is the open risk |

## Analysis plan, confirmatory contrasts (line 163)

Old:
> - Q3: for each model, judge-score gain minus truth-score gain

New:
> - Q3: for each model, the judge's false-positive rate among compiled outputs, GEPA arm minus seed arm (B minus A, D minus C). For a GEPA arm, the rate is computed per seed as a ratio of sums over items and then averaged over the 3 seeds; each bootstrap resample recomputes the ratio.
>
> Descriptive, with the same bootstrap and no decision rule: for each model, judge-score gain minus truth-score gain.

## Needs your call: the dated Q3 prediction (line 147)

Your prediction row is "Q3: judge gain minus truth gain, per model | Qwen3-8B +4 points, ReForm-8B +2 points | 40 | 2026-10-18". It was written for the old measure. Options:

1. Keep it as written, relabeled as a prediction for the descriptive gap.
2. Also add a new dated row for the false-positive measure, written before the GEPA pilot run, like the others (Changes, item 6).

## Unchanged

- Figure 2 stays "judge gain vs truth gain per model" (the descriptive gap). Its annotation now reads the descriptive contrasts.
- The hand-check sensitivity line (Q1 to Q3 on the random part) covers the new Q3. There the false positive is "judge faithful, hand label unfaithful".
