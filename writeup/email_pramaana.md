# Draft only (not sent): email to Pramaana

**To:** [name], Pramaana
**Subject:** A cheap LLM judge stayed steadily lenient under prompt optimization, without the gap growing

Hi [name],

I ran a small preregistered study on whether GEPA prompt optimization makes Lean 4 formalizers more faithful, and whether judge-measured gains overstate real ones. It used 247 ProofNet-Verified test items with Qwen3-8B and ReForm-8B, and GEPA optimized against a compile check plus a cheap LLM judge (gpt-oss-120b). All three preregistered answers came out inconclusive.

One exploratory result bears on optimizing against a judge. I gave truth labels (AXLE equivalence certificates first, then a separate reference judge) to every candidate prompt GEPA saved, on its 70 validation items. For ReForm-8B, the cheap judge scored all 31 candidates above truth, by about 6.1 points on average, but the gap did not grow as GEPA iterated: -0.09 points per iteration [-0.27, 0.08]. On the test set, the judge-measured gain from GEPA did not exceed the truth gain for ReForm-8B either (-0.9 points [-5.9, 4.0]). So here the judge looks steadily lenient rather than gamed, which is easier to correct for. It is one judge and one task, so I would not generalize far.

The code, prompts and every raw output with judge and truth labels are in the repo, which I'm happy to share. I'd be glad to hear whether you see steady offsets or growing gaps with your judges.

Thanks,
Neel Dankar
