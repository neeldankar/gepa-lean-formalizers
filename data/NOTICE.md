# Third-party data in `data/`

The datasets here are copies of other people's work, redistributed under their licences. The full licence texts are in `licenses/`. Licences were checked on 2026-10-25 at the pinned versions below.

## ProofNet-Verified

- **Source:** https://github.com/marcusm117/ProofNet-Verified, commit `160414332dc196583f6c37c310b420d2a3b07c58`
- **Licence:** Apache License 2.0 (the repository's `LICENSE` at that commit; copy in `licenses/Apache-2.0.txt`)
- **Paper:** One An, Marcus J. Min, Xujie Si, Osbert Bastani. "Ground False: Dissecting Errors in Formal Mathematics Benchmarks." 3rd AI for Math Workshop, 2026. https://openreview.net/forum?id=5c0RSYyIWW
- **Files here:**
  - `raw/proofnet-verified.jsonl` and `raw/memorization/data__proofnet-verified.jsonl`: `data/proofnet-verified.jsonl` from that commit, unchanged.
  - `proofnet_verified.jsonl`: **modified.** The same rows, mapped to this repo's item format by `src/data/proofnet.py`.
  - `splits.json`: this repo's train, validation and test split of those items.

ProofNet-Verified builds on these, and the copies below come from its `data/` folder at the same commit, unchanged:

| File here | Path in ProofNet-Verified | Origin | Licence |
|---|---|---|---|
| `raw/memorization/data__proofnet#__proofnet#.jsonl` | `data/proofnet#/proofnet#.jsonl` | ProofNet#, https://huggingface.co/datasets/PAug/ProofNetSharp (Poiroux, Weiss, Kunčak, Bosselut, 2024, arXiv:2406.07222) | MIT, per its dataset card; no licence file is published |
| `raw/memorization/data__proofnet__proofnet_lean4-6deae98.jsonl` | `data/proofnet/proofnet_lean4-6deae98.jsonl` | ProofNet-lean4, https://github.com/rahul3613/ProofNet-lean4, commit 6deae98 | MIT, Copyright (c) 2024 Rahul Vishwakarma (`licenses/MIT-ProofNet-lean4.txt`) |
| `raw/memorization/data__proofnet__proofnet-4.28.jsonl` | `data/proofnet/proofnet-4.28.jsonl` | A Lean 4.28 port of ProofNet, from the ProofNet-Verified authors | Apache 2.0, as part of ProofNet-Verified |

All of them derive from the original ProofNet, https://github.com/zhangir-azerbayev/ProofNet (Azerbayev, Piotrowski, Schoelkopf, Ayers, Radev, Avigad, 2023, arXiv:2302.12433). It is MIT licensed, Copyright (c) 2022 zhangir-azerbayev (`licenses/MIT-ProofNet.txt`).

`memorization_index.json` is **derived** from the four ProofNet files above: normalized statements, built by `src/scoring/memorization.py`.

## miniF2F (AI-MO version)

- **Source:** https://huggingface.co/datasets/AI-MO/minif2f_test, revision `5def318348521dfc34875045a9ecddf729a2b49f`
- **Licence:** Apache License 2.0 (`license: apache-2.0` on the dataset card at that revision; copy in `licenses/Apache-2.0.txt`)
- **Origin:** AI-MO corrected some statements of the miniF2F test set released with DeepSeek-Prover-V1.5, https://github.com/deepseek-ai/DeepSeek-Prover-V1.5 (MIT, Copyright (c) 2023 DeepSeek; `licenses/MIT-DeepSeek-Prover-V1.5.txt`).
  - That set adapts the original miniF2F, https://github.com/openai/miniF2F, whose Lean folder is Apache 2.0.
  - **Paper:** Kunhao Zheng, Jesse Michael Han, Stanislas Polu. "MiniF2F: a cross-system benchmark for formal Olympiad-level mathematics." arXiv:2109.00110, 2021.
- **Files here:**
  - `raw/minif2f_test.jsonl`: **converted.** The dataset's parquet rows at that revision, written as JSON lines, with the content unchanged.
  - `minif2f.jsonl`: **modified.** Mapped to this repo's item format by `src/data/minif2f.py`:
    - the docstring split off
    - `sorry` added
    - old `∑ x in s` binders rewritten to `∑ x ∈ s`
    - items whose reference does not compile dropped (243 of 244 kept)

## Changes

As Apache 2.0 section 4(b) asks, every file this repo changed is marked **modified**, **converted** or **derived** above. No upstream NOTICE file exists for either Apache-licensed source.
