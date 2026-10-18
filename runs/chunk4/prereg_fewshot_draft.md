# Draft prereg change: few-shot seed for arm A (not applied)

Drafted 2026-10-18 in chunk 4 at Neel's request. Neel edits and applies it, or doesn't. This is the last arm A change before the freeze. The code already does this (config `fewshot`, `prompts/fewshot.txt`, built by `python -m scripts.chunk4 fewshot`).

## Changes, new item

Number it 15 if the Q3 draft (`runs/chunk4/prereg_q3_draft.md`) goes in as item 14; otherwise 14.

> 15. **Arm A's seed prompt has three fixed train examples.**
>
> **The pilot.** Qwen3-8B with the one-line seed was truth-faithful on 2 of 30 pilot validation items, mostly because its outputs did not compile. Neel then added a block of Lean 4 syntax rules to the seed; that run was truth-faithful on 1 of 30, so the block was removed.
>
> **The examples.** The seed is now the original instruction line followed by a fixed few-shot block of three examples. Each example is laid out like a real query: the English statement, then that item's Lean context block (header and opens; none of the three has helper definitions), then the answer, its ProofNet-Verified reference statement ending in `:= by sorry`, in a ```lean4 block. The three are drawn with seed 0 from the 43 train items that have no helper definitions and whose reference compiles with `autoImplicit` off: pnv_218 (Dummit_Foote_exercise_1_3_8), pnv_226 (Dummit_Foote_exercise_3_2_16) and pnv_018 (Axler_exercise_4_4). No validation or test item is used.
>
> **Arms E and F.** Arm E (the checklist) and arm F (arm A's prompt on the frontier model) get the same block.
>
> **GEPA.** In arm B, GEPA optimizes only the instruction text. The examples are a fixed suffix that GEPA never sees or edits, so every GEPA candidate keeps the same three examples. The three example items are left out of GEPA's trainset, because their answers are in the prompt. Every GEPA run, arm B and arm D alike, trains on the other 47 train items, so the two models are optimized on the same items. The validation set (70 items) and the split file are unchanged.
>
> **Arms C and D** are unchanged: ReForm-8B's own prompt (Changes, item 11), with no examples.
>
> This is the last change to arm A before the freeze.

## Arms table

Old:
> | A | Qwen3-8B | Plain seed prompt | none | Core: general model, before |
> | B | Qwen3-8B | GEPA, starting from A's prompt | 3 | Core: general model, after |
> | E | Qwen3-8B | A careful hand-written checklist prompt: list every hypothesis, check number types, check quantifiers. Drafted by Claude from the task description and edited by Neel, before any GEPA output exists. | none | Does GEPA beat a person spending 30 minutes on a prompt? |
> | F | One frontier model | Plain seed prompt | none | Ceiling reference, test set only |

New:
> | A | Qwen3-8B | Seed prompt: one instruction line plus three fixed train examples (Changes, item 15) | none | Core: general model, before |
> | B | Qwen3-8B | GEPA, starting from A's instruction line; the three examples are a fixed suffix GEPA can't edit | 3 | Core: general model, after |
> | E | Qwen3-8B | A careful hand-written checklist prompt: list every hypothesis, check number types, check quantifiers. Drafted by Claude from the task description and edited by Neel, before any GEPA output exists. Followed by arm A's three examples. | none | Does GEPA beat a person spending 30 minutes on a prompt? |
> | F | One frontier model | Arm A's seed prompt, with its three examples | none | Ceiling reference, test set only |

## Notes for Neel (not prereg text)

1. **The reflection model never sees the examples.** It sees only the instruction text it rewrites. It could write rules that repeat or contradict the examples; the examples still go with every call.
2. **The theorem names are ProofNet-Verified's**, for example `Dummit_Foote_exercise_1_3_8`. Normalization renames every candidate to a fixed name before any judge sees it, so a model copying that naming style changes nothing downstream.
3. **Resolved since the first draft:**
   - The trainset overlap: the example items are out of every GEPA trainset.
   - Example 3's `@card`: its context block now shows `open Fintype ...`.
4. **Arm D also trains on 47 items.** It has no examples, but leaving the same three items out of its trainset keeps B and D comparable for Q2. Tell me if you'd rather D keep all 50.
