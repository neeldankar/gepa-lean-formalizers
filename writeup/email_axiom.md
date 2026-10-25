# Draft only (not sent): email to Axiom

**To:** [name], Axiom Math
**Subject:** GEPA on an 8B Lean formalizer: the gain was compiling, not meaning (AXLE-checked)

Hi [name],

I ran a small preregistered study on whether GEPA prompt optimization makes Lean 4 formalizers more faithful. It used 247 ProofNet-Verified test items, with Qwen3-8B and ReForm-8B, and GEPA optimizing against a compile check plus an LLM judge. AXLE did all the Lean checking, including the equivalence certificates I used as the first source of truth labels.

One finding seems relevant to how you tune formalizers. For Qwen3-8B, GEPA's truth gain (+2.8 points, interval [-0.4, 6.6], inconclusive) splits into a compile part of +3.3 points [1.1, 6.3] and a meaning part of -0.4 [-4.2, 3.5]. Compile rate went from 11.7% to 20.4%, but the faithful share among compiled outputs did not rise (37.9% to 35.8%). The optimized prompts are mostly lists of Lean 4 syntax traps and Mathlib names that do not exist.

The code, prompts and every raw output with judge and truth labels are in the repo, which I'm happy to share. I'd value your view on whether that matches what you see when optimizing against a compile-plus-judge signal.

Thanks,
Neel Dankar
