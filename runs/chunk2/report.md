- References compiled with autoImplicit off (information only): 363/367
  - pnv_025: -:7:70-7:71: error(lean.unknownIdentifier): Unknown identifier `F`
  - pnv_207: -:7:71-7:72: error(lean.unknownIdentifier): Unknown identifier `F`
  - pnv_208: -:7:70-7:71: error(lean.unknownIdentifier): Unknown identifier `F`
  - pnv_280: -:8:8-8:11: error(lean.unknownIdentifier): Unknown identifier `f_a`
- Duplicate Rudin_exercise_4_8a (pnv_168, pnv_351, splits ['test', 'test']): identical False, differs in ['informal_stmt', 'formal_stmt']
- Stripper contest: ours 14/14, AXLE remove_comments 13/14; winner: ours
  - AXLE failed 'single primed name then comment': output "theorem t (x' : ℕ) : x' = x' := rfl -- the judge should say faithful"
- Golden cases: 14/14 pass; certificates: on

| Case | Expected | Got | Pass |
| --- | --- | --- | --- |
| exact copy | compiled=true; certified=true; truth_label=faithful | compiled=true; certified=true; truth_label=faithful | yes |
| a < b written as b > a | compiled=true; certified=true; truth_label=faithful | compiled=true; certified=true; truth_label=faithful | yes |
| reordered hypotheses | compiled=true; certified=true; truth_label=faithful | compiled=true; certified=true; truth_label=faithful | yes |
| hypothesis dropped | compiled=true; certified=false; judge_verdict=unfaithful; truth_label=unfaithful | compiled=true; certified=false; judge_verdict=unfaithful; truth_label=unfaithful | yes |
| ℕ where the text says integers | compiled=true; certified=false; truth_label=unfaithful | compiled=true; certified=false; truth_label=unfaithful | yes |
| swapped quantifier | compiled=true; certified=false; truth_label=unfaithful | compiled=true; certified=false; truth_label=unfaithful | yes |
| comment claiming faithfulness | compiled=true; certified=false; truth_label=unfaithful; never_reaches_judge=["faithful translation", "verified by experts", "answer faithful"] | compiled=true; certified=false; truth_label=unfaithful; never_reaches_judge=["faithful translation", "verified by experts", "answer faithful"] | yes |
| does not compile | compiled=false; judge_score=0; truth_label=unfaithful | compiled=false; judge_score=0; truth_label=unfaithful | yes |
| invented dotted name Nat.IsGoodPrime | compiled=false; judge_score=0; truth_label=unfaithful | compiled=false; judge_score=0; truth_label=unfaithful | yes |
| invented plain name (autoImplicit off) | compiled=false; judge_score=0; truth_label=unfaithful | compiled=false; judge_score=0; truth_label=unfaithful | yes |
| long ReForm-style output | compiled=true; certified=true; truth_label=faithful; normalized_contains=(h : a > 1) | compiled=true; certified=true; truth_label=faithful; normalized_contains=(h : a > 1) | yes |
| no Lean in the output | format_failure=true; compiled=false; judge_score=0; truth_label=unfaithful | format_failure=true; compiled=false; judge_score=0; truth_label=unfaithful | yes |
| true but unrelated statement | compiled=true; certified=false; truth_label=unfaithful; r2c_discarded=true | compiled=true; certified=false; truth_label=unfaithful; r2c_discarded=true | yes |
| string literal with -- survives stripping | compiled=true; normalized_contains="a--b".length = 4; never_reaches_judge=["trailing comment"] | compiled=true; normalized_contains="a--b".length = 4; never_reaches_judge=["trailing comment"] | yes |

- Judge cost per call (chunk 2, $0.0296 over 49 paid calls):
  - opt_judge (openai/gpt-oss-120b): 10 calls, $0.000304 per call
  - ref_judge (deepseek-ai/DeepSeek-V4.1-Flash): 10 calls, $0.000751 per call
  - probe (zai-org/GLM-5.3-Flash): 3 calls, $0.000114 per call
  - gloss (zai-org/GLM-5.3-Flash): 26 calls, $0.000721 per call
- Memorization index: 644 distinct statements; sources {'ProofNet-Verified': {'rows': 367, 'keys': 367}, 'ProofNet#': {'rows': 371, 'keys': 371}, 'ProofNet-lean4 (6deae98)': {'rows': 374, 'keys': 360}, 'ProofNet (Lean 4.28 port)': {'rows': 367, 'keys': 353}}; skipped {'ProofNet (original)': 'Lean 3 only'}; train references matching themselves: 50/50

