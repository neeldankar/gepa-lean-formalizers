# Draft prereg note: go criterion 1 not met (not applied)

Drafted 2026-10-22 in chunk 4 at Neel's request. Neel edits and applies it, or doesn't. Numbers from `runs/chunk4/block2_numbers.json`.

## Pilot and go criteria: add after the "Go if all of these hold" list

> **Pilot result (2026-10-22).** Go criterion 1 is not met: with the final seed (arm A's instruction line plus the few-shot block), Qwen3-8B was truth-faithful on 6.7% of the 30 pilot validation items (2 of 30), below the roughly 10% floor. The earlier seeds gave 6.7% and 3.3%. The other three criteria are met: the reference judge agrees with Neel's labels on 19 of 20 items, exact matches are 0% in every configuration, and the projected total is at most about $94.
>
> We proceed because:
> 1. The criterion is there to leave room to move. At 6.7% there is plenty of room upward; the risk is only a floor effect for B minus A.
> 2. ReForm-8B is at 46.7% (14 of 30), inside the range, so D minus C is unaffected.
> 3. The main question, whether judge-measured gains overstate real ones (Q2, Q3), needs compiled outputs and judge verdicts, not a minimum faithful rate.
> 4. Changing the formalizer now would be a design change after Neel's dated predictions.
>
> Consequence: Qwen3-8B's results are read with the floor in mind. A null for B minus A says GEPA did not lift a model near the floor, not that it cannot help a stronger one.
