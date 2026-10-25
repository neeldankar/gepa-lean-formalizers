# GEPA on Lean formalizers

A preregistered study of two questions:
- Does GEPA prompt optimization make Lean 4 formalizers more faithful? It was tested on Qwen3-8B (a general model) and ReForm-8B (a fine-tuned formalizer).
- Do gains measured by a judge overstate the real ones?

The plan is `prereg.md`, frozen at tag `prereg-frozen` before any test output existed; later changes are in its dated Deviations section. The writeup is `writeup/writeup.md`, and `LOG.md` records every run, its cost and every decision.

**Answer in one line:** all three preregistered questions are inconclusive. For Qwen3-8B, the measured gain is mostly from compiling more often. The details are in the writeup.

## What is where

| Path | What |
|---|---|
| `prereg.md` | The preregistration: questions, arms, scoring, analysis, deviations |
| `CHUNKS.md`, `LOG.md` | The work plan by chunk, and the dated run log (every run, cost and decision) |
| `config.yaml` | Every setting: models, judges, AXLE, GEPA budget, analysis, budget caps |
| `prompts/` | Seed prompts (`arm_A.txt`, `arm_C.txt`, `arm_E.txt`), the few-shot block, both judge prompts, the gloss prompt |
| `runs/{B,D}_s{0,1,2}/best_prompt.txt` | The six GEPA-optimized prompts; `candidates/` holds every candidate GEPA saved, with its validation outputs and judge scores |
| `runs/final/{A..F}.jsonl.gz` | Every final-eval output (test and miniF2F): raw output, normalized statement, compile status, judge verdict, certificate, reference verdict, truth label |
| `runs/handcheck/` | The blind hand-check: `sample.jsonl` (the hidden mapping), `labeling.html` (the page), `labels.csv` (Neel's labels), `provenance/` (how the labels were recorded) |
| `results.json`, `figures/` | Output of the frozen analysis (`scripts/analyze.py`) and the two preregistered figures; `figures/exploratory_*` are exploratory |
| `runs/chunk7/` | Exploratory analyses and the writeup checks |
| `data/` | ProofNet-Verified and miniF2F as loaded (`proofnet_verified.jsonl`, `minif2f.jsonl`), the train/validation/test split, the memorization index |
| `src/`, `scripts/`, `tests/` | Library code, one entry script per chunk, pytest tests |

## Setup

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
bash scripts/install_hooks.sh      # secret scan as pre-commit and pre-push hooks
python -m pytest -q                # all tests run offline on mocks
```

`.env` (gitignored) holds the keys, by name:
- `TOGETHER_API_KEY`: the judges, the gloss model and Kimi-K3 before Deviation 2
- `OPENROUTER_API_KEY`: Kimi-K3 after Deviation 2
- `AXLE_API_KEY`: Lean checking
- `GITHUB_TOKEN` and `RUNPOD_POD_ID`: pod jobs only

Model calls, judge calls and AXLE calls are cached on disk in `cache/`, keyed by a hash of their full inputs. `cache/` is not committed.

## Reproducing

**From the committed raw outputs (exact).** This reruns the analysis on the outputs as generated, and should give `results.json` exactly:

```bash
python -m scripts.analyze --labels runs/handcheck/labels.csv --sample runs/handcheck/sample.jsonl
python -m scripts.chunk6 validate     # labels.csv against the sample
python -m scripts.chunk7 check        # every writeup number against its JSON source, em dash and secret scans
```

**From scratch (the full pipeline).** Run the chunks in order. Each script's docstring lists its steps:

1. `python -m scripts.chunk1`: load both datasets, compile every reference statement, make the split (laptop, AXLE).
2. `python -m scripts.chunk2` and `python -m scripts.chunk3`: scoring checks, runner checks and a dry run on mocks.
3. The chunk 4 pilot, on an H100 pod:
   - `bash scripts/setup_pod.sh` sets up vLLM and both formalizers.
   - `python -m scripts.chunk4 gen | armf | label | gepa | agree` runs the steps; `scripts/chunk4_pod_queue.sh` runs them unattended.
4. Chunk 5, the main job on the pod:
   - `bash scripts/run_job.sh chunk5 python -m scripts.chunk5_job` runs six GEPA runs (B and D, 3 seeds each, 800 metric calls each), then the final eval of arms A to F. It pushes the results and stops the pod.
   - On the laptop: `python -m scripts.chunk5_job check` for the health checks, and `python -m scripts.chunk5_job deviation4` for Deviation 4's re-ask.
5. Chunk 6, the hand-check:
   - `python -m scripts.chunk6 sample` builds the blind page. Label it, then export `labels.csv`.
   - Then run `scripts.analyze` as above, and `python -m scripts.chunk6 compare` against an independent recompute.
6. Chunk 7, exploratory: `python -m scripts.chunk7 prompt-lengths | facts | candidate-truth | compile-errors`.

**Expect differences from scratch:**
- Without `cache/`, a from-scratch run repeats every model, judge and AXLE call. Every logged cost is in `runs/costs.jsonl`.
- Generation used vLLM with fixed seeds and the API models at the settings in `config.yaml`, but outputs need not be byte-identical across hardware, library versions, provider serving, or Kimi-K3 after Deviation 2 (no `seed` field).
- The exact path to every number in the writeup is the committed raw outputs plus the analysis command above.

## Rules this repo kept

- GEPA code can load only the train and validation items; a test enforces it.
- No test or miniF2F output was generated before every GEPA run finished.
- No per-arm test score was looked at before the hand labels were in.
- Every number in `LOG.md` and the writeup comes from a script that writes JSON. `writeup/numbers.json` maps each writeup number to its source, and `scripts/chunk7.py check` verifies them.
