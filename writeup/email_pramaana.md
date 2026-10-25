# Draft only (not sent): email to Pramaana

**To:** [name], Pramaana
**Subject:** How often an LLM reference judge got Lean faithfulness wrong against hand labels

Hi [name],

I ran a small preregistered study on whether GEPA prompt optimization makes Lean 4 formalizers more faithful, and whether judge-measured gains overstate real ones. It used 247 ProofNet-Verified test items, with Qwen3-8B and ReForm-8B. All three answers came out inconclusive, but one finding bears directly on judge-based evaluation.

I hand-labeled a blind random sample of compiled outputs and compared them with the reference judge (DeepSeek-V4.1-Flash). It agreed on 89 of 99. Its errors leaned one way: 8 false negatives (faithful statements called unfaithful) against 2 false positives. Agreement was much lower on the weaker model's outputs (4 of 7 and 13 of 16 for Qwen3-8B's two arms) than on ReForm-8B's (36 of 38 in each). The samples are small, but it suggests a judge's error rate can depend on whose outputs it is grading, which matters when one model is compared with another.

The code, prompts, raw outputs and hand labels are in the repo, which I'm happy to share. I'd be glad to hear whether this matches what you see with your judges.

Thanks,
Neel Dankar
