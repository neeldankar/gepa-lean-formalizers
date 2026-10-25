# Rules GEPA wrote into the six optimized prompts (exploratory)

Read from `runs/{B,D}_s{0,1,2}/best_prompt.txt` and compared with the seed prompts: `prompts/arm_A.txt` for B (Qwen3-8B) and `prompts/arm_C.txt` for D (ReForm-8B). Both seeds are one or two sentences long. This is a reading of the prompts, not a measurement: it is not tied to any score, and it says nothing about which rule helped.

## Rules that appear in all six

- **The compile gate is spelled out.** A statement that does not compile scores 0, and faithfulness is only checked after it compiles (B_s0 "Correctness requirement (critical)", D_s0 "Hard gate", D_s2 "CRITICAL: the statement MUST compile").
- **Keep every hypothesis; don't weaken or strengthen.** Each prompt asks for every stated hypothesis as a named binder and for a statement neither weaker nor stronger than the problem.
- **Mentally compile and re-check before answering**, as a numbered checklist or procedure.
- **Respect the item's Lean context.** Use its definitions and notations exactly as declared, and don't repeat or redefine them.

## Rules about compiling (Lean 4 and Mathlib)

| Rule | Runs |
|---|---|
| Never invent identifiers, with warnings naming identifiers that do not exist (for example `Im`, `Re`, `ConstantOn`, `IsSimple`, `OpenSet`, `Nat.phi`, `GaussianInt.mk`, `Set.unitCircle`, `Complex.norm`). AXLE confirms all 14 names they call nonexistent are absent; but 4 names they present as usable are absent too (`Complex.abs`, `FiniteDimensional.finrank`, `Set.IsConnected`, `Set.Uncountable`; `runs/chunk7/prompt_names.json`) | B_s0, B_s1, B_s2, D_s1, D_s2 |
| No Lean 3 lambdas (`λ x, ...`); write `fun x => ...` | B_s0, B_s1, B_s2 |
| `λ` is reserved and cannot be a variable name; rename an eigenvalue to `μ` | B_s0, D_s1, D_s2 |
| Typeclasses are not types: `(X : Type*) [TopologicalSpace X]`, and instances must be synthesizable | B_s0, B_s1, B_s2, D_s2 |
| Explicit coercions: numeric casts, polynomial coefficients via `C`, subtype inclusions such as `⟨x, subset_closure hx⟩` | B_s1, B_s2, D_s0, D_s2 |
| Avoid or be careful with `let` inside a theorem statement | D_s1, D_s2 |
| Bounded quantifiers take one binder per `∈`; `⋂`/`⋃` (big) vs `∩`/`∪` (binary) | B_s0, B_s2 |
| Always emit a closed code block, never an empty answer | B_s1 |
| Prefer predicates and quantifiers over subtypes and heavy structures | D_s2 (also D_s0 for subtypes) |

## Rules about meaning

| Rule | Runs |
|---|---|
| "The order of x is n" is `orderOf x = n`, not the weaker `x ^ n = 1`; literal equations stay literal | B_s1, B_s2, D_s2 |
| "Not necessarily" or "not true in general" is a counterexample (`∃ ... ∧ ¬ ...`), not `∀ ... → ¬ ...` | B_s1, B_s2, D_s2 |
| "f is constant on S" is `∃ c, ∀ z ∈ S, f z = c` | B_s0, B_s1, B_s2 |
| Keep the stated domain and strength (an open set Ω stays Ω; holomorphic is `DifferentiableOn ℂ f Ω`, not `ContinuousOn`) | B_s0, B_s1, B_s2 |
| "Infinitely many" is `Set.Infinite {a | ...}` | B_s1 |
| Formalize the full strength of the conclusion (for example a condensation point) | D_s1 |
| Every "where" clause is a hypothesis binder | B_s2 |

## Item-specific content

- **Worked statements copied from GEPA's own items.** B_s0, B_s1, B_s2 and D_s2 include complete theorem statements for specific problems GEPA saw in training or validation, for example the RSA key property, limsup over `EReal`, countable compactness, Gaussian-integer divisibility, and unique extension to the closure. D_s0 and D_s1 carry fragments of specific items instead: the closure-extension agreement condition, the condensation-point conclusion, and the context names `Rl` and `K_topology`.
- **Overfitting risk.** Much of the prompt text is about the particular items GEPA saw, not general guidance. This fits the small difference on the test split, but this study cannot tell whether that is the reason.
- **No test leakage.** GEPA saw only train and validation items, so these examples are not test items. Some test items are close relatives; for example, the test item "|f| constant implies f constant" resembles the validation item "Im(f) constant implies f constant".

## Length

Each optimized prompt is much longer than its seed. The word counts are in `runs/chunk7/prompt_lengths.json`.
