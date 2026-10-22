# LOG

## Now

- **Chunk:** 5 of 7, session 1 done: the combined job is running on pod 6 (relaunched 2026-10-22 06:37 UTC after Deviation 1). `prereg.md` frozen at e631bdb; Deviations only (1 so far)
- **Status:** the chunk 5 job ended 2026-10-22 08:44 UTC, exit 1, results pushed (5a2dcc4); pod 6 refuses SSH (stopped by the job; Neel to confirm in RunPod). D_s0 DONE; B_s0, B_s1, B_s2, D_s1, D_s2 STOPPED on reflection retries (Kimi-K3 on Together). No final eval yet.
- **Next:** resume on a new pod with Kimi-K3 through OpenRouter pinned to Together (Deviation 2): the 5 stopped runs, then the final eval. Then session 2's checks (invariants and health only, no per-arm scores).
- **Spent so far:** $31.81 of $300 logged; chunk 5 $20.48 metered plus $1.42 unmetered pod time (cap $180)
- **Waiting on Neel:** the pod's SSH line for the resume.
- **At the freeze (Neel's item 7):** a list of at most 15 lines, every component added since the Oct 17 design doc, one line each on why; nothing removed.
- **Pod rule (Neel):** never terminate; keep it running for the pilot; stop only after the queue ends or if idle more than about 30 min; push before any stop.
- **Parked ideas** (chunk 7 only, exploratory; older ones in the chunk 1 to 4 entries):
  - Compile-error taxonomy: classify Lean compile failures per arm (unknown identifier, parse error, type error, ...).
  - Judge vs truth over GEPA iterations: a figure from the saved candidate outputs in `runs/<run_id>/candidates/` (item 2 data).
  - ReForm-8B training-data contamination: note whether ProofNet-style statements could be in ReForm-8B's training data.

## Entries

Newest first. One entry per chunk session and per run, including failed or discarded runs.

Template:

```
### YYYY-MM-DD · chunk N · short title
- Did:
- Numbers: (from <file>.json; subagent check: match / mismatch)
- Cost: $X this entry, $Y total
- Problems:
- Next:
```

### 2026-10-22 · chunk 5 · Deviation 2: Kimi-K3 through OpenRouter pinned to Together; route checked live

- **Neel's choices:** skip the Together preflight (yesterday's pass did not predict the night). Route Kimi-K3, for reflection and arm F, through OpenRouter pinned to Together (`provider.only: [together]`, fallbacks off, `require_parameters: true`). Rejected: Moonshot's own serving, which fixes kimi-k3 at temperature 1.0; we use 0.0 for reflection and 0.6 for arm F. Prereg Deviation 2.
- **Found while preparing:** GEPA 0.1.4 evaluates the seed prompt on the full val set before it loads `gepa_state.bin` (`core/engine.py` run()), then discards the result. So D_s0 would not end at once on resume: it would redo 70 items and overwrite its saved seed outputs. Last night's relaunch did this too, but with the pod's cache in place the outputs were identical. Fixes: `chunk5_job` skips runs with DONE (`skipped (done)`; the sanity check still checks them), and `save_candidate` never overwrites an existing file. The 5 resumed runs still do one discarded seed pass each. `candidates.json` `adapter_metric_calls` counts only the last process; GEPA's `total_metric_calls` is unaffected.
- **Code:** `LLMClient` gets `extra_body` and `drop_params` (applied before the cache key), logs `provider` from the reply, retries replies without `choices` and HTTP 408. New `reflection_client` (`gepa.reflection_host: arm_f`) in `gepa_run`, `preflight` and `reflect_load`. Config: arm F on `https://openrouter.ai/api/v1`, `moonshotai/kimi-k3`, `OPENROUTER_API_KEY`, `drop_params: [seed]`, price $3 / $15 per 1M (OpenRouter's Together endpoint). Tests: 211 pass (6 new).
- **Failure counts in the job window** (06:12 to 08:44 UTC, from `runs/chunk5/kimi_route_check.json`): 53 failed Kimi-K3 attempts, 46 HTTP 503 (all 339 to 341 s), 7 HTTP 429. My earlier "58" counted preflight failures from Oct 21 too.
- **Live route check** (laptop, 18:42 to 18:52 UTC, same file; logs `runs/chunk4/preflight_2026-10-22/openrouter_together_*.log`):
  - 6 of 6 concurrent 3-record reflections pass (53 to 535 s, all finish stop, $0.90).
  - The preflight reflection passes (57 s, stop).
  - Arm F on pnv_004 hits the 16,384-token cap (finish length, no Lean statement, 303 s). The same item went 6,849 / 16,384 / 11,612 tokens on Together's own API (Oct 18, Oct 21, Oct 22); the cap is Neel's, kept at the freeze.
  - All 8 Kimi-K3 rows report provider Together; 0 failed attempts; $1.20 (chunk 4 rows, the script's `CHUNK`).
  - The slowest reflection, 535 s, is near the 600 s per-attempt limit.
- The chunk 4 load-check record is kept as `runs/chunk4/reflection_load_2026-10-22T0232_together.json`.
- **Cost:** $1.20 this entry.

### 2026-10-22 · chunk 5 · job ended: 1 of 6 GEPA runs done, no final eval

- **Run chunk5 (relaunch) outcome** (from `runs/chunk5_job_end.json`): ended 08:44 UTC, exit 1, pushed (commit 5a2dcc4). The sanity check failed as expected. D_s0 DONE (869 metric calls, sanity limit 873; 12 reflections). B_s0, B_s1, B_s2, D_s2 STOPPED after 5 attempts with HTTP 503; D_s1 after 5 attempts with HTTP 429 ("all replicas at capacity"). 44 failed reflection attempts since the relaunch (40 HTTP 503, 4 HTTP 429), the last at 08:38 UTC. No scores read.
- **Cost:** chunk 5 $20.48 metered, plus $1.42 unmetered pod time; $31.81 logged in total.
- **Next:** superseded by Deviation 2 (entry above).

### 2026-10-22 · chunk 5 · Kimi-K3 mostly down; two runs stopped; letting the job run out (Neel)

- **Numbers** (from `runs/chunk5_health_0740.json`, counts since the 06:37 relaunch, at 07:50 UTC): 28 failed reflection attempts, all HTTP 503 after about 340 s. B_s0 stopped at 07:32 UTC (`gave up after 5 attempts`, HTTP 503), and B_s1 stopped the same way. Still running: B_s2 (iteration 9), D_s0 (17), D_s1 (18), D_s2 (12). Chunk 5 spend $15.95 by 07:50 UTC.
- **Neel's choice** (option 1 of 3): let the job run out. The other runs keep going; the sanity check then fails, and the job pushes everything and stops the pod. No final eval in this job. Rejected: pausing now (would also pause the working D runs); another Kimi-K3 provider (a deviation, and maybe served differently); the GLM-5.3 fallback (reflection model would differ across seeds).
- **Resume plan:** when the preflight gate opens, use a new pod and rename each STOPPED marker (keep it as a record). Rerun `run_job.sh chunk5 python -m scripts.chunk5_job`: finished runs return at once, stopped runs resume from `gepa_state.bin`, then the final eval runs.
- **Cost:** $0 this entry.

### 2026-10-22 · chunk 5 · session 1: launch, Deviation 1, relaunch

- **Pod 6:** H100 80GB HBM3, id `qybccgbwec39wd`, 50 GB container disk, no network volume. Repo copied by rsync (no `cache/`, so every call is live). Setup 05:51 to 05:59 UTC, both servers healthy.
- **API preflight** (laptop, `chunk4 preflight --fresh --cap 600`, 05:51 to 06:11 UTC; log `runs/chunk4/preflight_2026-10-22/chunk5_launch_full_cap600.log`; numbers from `runs/chunk5_launch_health.json`): gate open. 3-record reflection pass, 281 s, 13,329 out tokens, $0.20. Arm F pass, 222 s, 11,612 out tokens, finish stop, $0.18. All 4 judge checks pass. 15-record reflection fail (HTTP 503 on both attempts; information only, as on Oct 22). Its cost rows are logged as chunk 4 (the script's `CHUNK`).
- **Run chunk5, launch 1** (06:12:17 UTC, `run_job.sh chunk5 python -m scripts.chunk5_job`, frozen config): all six runs iterated, but Together's Kimi-K3 failed 9 reflection attempts in 24 min (HTTP 429 `worker_stream_failed`, and HTTP 503 after about 340 s). B_s2 stopped (ReflectionFailed after 2 attempts), and B_s0 had used up its retries on one call. Either would have made the sanity check fail after the other runs, with no final eval. Stopped by me at 06:36 UTC (tmux session first, so the job body neither pushed nor stopped the pod); state committed on the pod (87d150e). Chunk 5 spend at the stop: $3.80.
- **Deviation 1** (Neel, that night; prereg Deviations item 1; commit e281db5): reflection retries 1 to 4, waits about 30, 60, 120, 240 s with +-20% jitter; on a 429, Retry-After wins when longer (at most 600 s). Jitter and Retry-After apply to every API retry (timing only). Before: 5 s x 2^attempt, no jitter, Retry-After ignored. 6 new tests (205 pass on the laptop; `tests/test_llm.py` 14 pass on the pod). B_s2's old marker is kept as `runs/B_s2/STOPPED_before_relaunch_2026-10-22`.
- **Bug found:** my second rsync copied the laptop's `.git/config` over the pod's and dropped the git identity, so `run_job.sh`'s final results commit would have failed and the pod would have stopped without pushing. Fixed with `git config --global` on the pod. Future pods: set the identity globally before any rsync.
- **Run chunk5, relaunch** (06:37:03 UTC, same command): every run resumed from its saved GEPA state (1 seed val pass each, iteration numbers continued). By 06:54 UTC: iterations B_s0 3 to 5, B_s1 3 to 6, B_s2 3 to 4, D_s0 4 to 7, D_s1 4 to 8, D_s2 4 to 6; reflections since the relaunch 2 / 3 / 1 / 3 / 4 / 2; 0 STOPPED, 0 new tracebacks. 4 failed attempts (all HTTP 503 after about 340 s), each retried after the backoff; B_s0, B_s2 and D_s2 went on after them. No scores read or shown.
- **Not metered by the job:** pod time from 05:51 (setup) to 06:12 and the 1 min between the stop and the relaunch: 0.356 h, $1.42 at $3.99/hr (from `runs/chunk5_launch_health.json`); session 2 logs it as a balancing row, as in chunk 4.
- **Cost:** preflight $0.38 (chunk 4 rows); chunk 5 $6.91 metered by 06:54 UTC (API and GPU), plus the $1.42 above. `runs/costs.jsonl` as pushed (rows to 06:36 UTC) totals $15.13; the pod's later rows arrive with the job's push.

### 2026-10-22 · chunk 4 · freeze tagged; chunk 4 done

- **Did:** Neel's OK on the diff; `git tag -a prereg-frozen` on e631bdb, pushed after a history secret scan. Pod 4 confirmed stopped (Neel). 199 tests pass.
- **Five random raw examples** (pilot rows, `random.Random(4)`): qwen_nothink pnv_020 (Lean 3 class names, `λ` as a variable: no compile, truth unfaithful); qwen_nothink pnv_239 (binders inside `¬∃`: no compile); qwen_a2 pnv_333 (`α` used as type and variable: no compile); qwen_think pnv_158 (`Complex.abs` form: no compile, 2,258 tokens); reform pnv_024 (compiles; opt judge unparseable, now missing; ref judge unfaithful; truth unfaithful, matching Neel's label P01).
- **Cost:** $0 this entry.

### 2026-10-22 · chunk 4 · freeze prepared (not tagged)

- **Neel's picks** (2026-10-22, all as recommended in Block 2): arm F on `moonshotai/Kimi-K3` at the shared 16,384-token cap, arm F budget line about $25; temperature 0.6, 1 sample; optimization judge `openai/gpt-oss-120b`; reference judge `deepseek-ai/DeepSeek-V4.1-Flash`; reflection `moonshotai/Kimi-K3`; GEPA budget 800; threshold 5 points. All four drafts applied (Changes 14 Q3, 15 few-shot, 16 analysis additions, the go-criterion-1 note with Neel's reason 4).
- **New rule (Neel), Changes item 17:** a judge reply still unparseable after one re-ask is a missing verdict, never faithful or unfaithful. Code: `judge.py` returns `verdict: "missing"`; `judge_score` None with `judge_missing`; truth label None (`ref_judge_missing`) unless a certificate settles it; final eval keeps such rows (not outages); analysis leaves them out of that arm's rates (NaN per item; the false-positive rate and compile/meaning split use only items with the needed values) and reports `missing_opt_judge`, `missing_ref_judge`, `missing_truth_label` per arm; `chunk4 agree` counts missing apart. Choice the rule left open: inside GEPA a missing opt-judge verdict scores 0 (GEPA needs a number) and the feedback says the reply could not be read. Tests: 199 pass.
- **Pilot agreement under the rule** (`chunk4 agree`): reference judge 19 of 19 with a verdict (1 missing, P20), truth label 19 of 19 (1 missing, P20), optimization judge 16 of 19 (1 missing, P01). Pilot rows themselves are not rescored: P20's stored truth label is still "unfaithful" (recorded before the rule); no go number changes (qwen_a3 has no missing verdict).
- **Subagent check** (fresh agent, raw files and prereg only, no `src/` or `scripts/`; `runs/chunk4/subagent_check_freeze.json`): match on every count and rate per configuration (compile, format failures, truth faithful, judge score, certified, exact match, length stops, token mean / median / max), agreement 19/19, 19/19, 16/19 with 1 missing each, go criteria, GEPA pilot (158 calls = 70 + 6 x 3 + 70 x 1; 3 reflections; val 0.0571 seed best, 0.0286 candidate), reflections per run 24.89 / 9.61 / 121.67, reflection $0.0969 mean and 121.2 s (element n//2; the two-middle median would be 116.1 s), arm F GLM-5.3 1 compiled / 4 at the cap / max 16,384, dry run Kimi-K3 4 / 0 / 5,470, spend chunk 4 $10.92 and total $10.95. Its one flag is the P20 pilot row above.
- **At the freeze (Neel's item 7), added since the Oct 17 design doc:**
  1. One H100 with vLLM for both formalizers: same sampling code; Featherless too limited.
  2. Reference judge on every compiled item: so certificate vs judge disagreements can show.
  3. Judge error rate from the random hand-check part only, disagreement part capped at 25: unbiased error estimate.
  4. Labeling page glosses each statement alone: labels can't anchor on the judge.
  5. Error tags from the reference judge, same call as its verdict: one call, consistent tags.
  6. gepa 0.1.4 pinned, library defaults, small custom adapter: no existing GEPA pipeline.
  7. One scripted miniF2F binder rewrite; non-compiling items dropped and counted: no hand fixes.
  8. autoImplicit off for candidates: unknown names would compile silently.
  9. Arm C uses ReForm-8B's released prompt: a weaker seed would inflate D minus C.
  10. Faithful means logically equivalent; certificate vs judge conflicts to the hand-check: clear truth definition.
  11. Hand-check paired across the four core arms: paired bootstrap at about 100 labels.
  12. Few-shot block of 3 train examples for arms A, B, E, F: Qwen3-8B rarely compiled with the one-line seed.
  13. Q3 as the judge false-positive rate, plus three analysis additions: the old gap moved with compile rate alone.
  14. Missing judge verdicts never scored, counted per arm: an unreadable reply is not evidence either way.
  15. Run safety: per-call timeouts and retry caps, live API preflight gate, saved GEPA candidate outputs, chunk 5 combined job with a dry run: Kimi-K2.6 outage and Kimi-K3 hangs.
- **Cost:** $0 this entry.

### 2026-10-22 · chunk 4 · Block 2: arm F on GLM-5.3, labels, projection

- **Arm F on GLM-5.3** (Neel's option b; `config.yaml` `models.arm_f.served_name: zai-org/GLM-5.3`, price $1.40 / $4.40 per 1M). `chunk4 armf --ids` on the dry run's 5 train items (pnv_004, 011, 019, 029, 042), now with arm F's few-shot block and a compile check; run id `pilot_arm_f`. Outcome: compiled 1 of 5; 4 of 5 used all 16,384 tokens on reasoning and returned no text; max 16,384 tokens; 9 to 134 s; $0.30. Probe with `enable_thinking: false` (config unchanged, run id `probe_arm_f_glm53_nothink`): 0 of 5, all 5 at the cap, flag ignored; $0.36. Files `runs/chunk4/arm_f_glm53*.json*`. Same items on Kimi-K3 in the dry run: 5 of 5 under the cap, 4 compiled.
- **Labels** (Neel, new page, 20 items; `runs/chunk4/labels.csv`, `chunk4 agree`): reference judge 19 of 20, truth label 20 of 20, optimization judge 16 of 20. Misses: ref judge unparseable on P20; opt judge faithful on 2 unfaithful ReForm-8B items, unfaithful on 1 certified item, unparseable on 1. 10 of 20 labeled faithful, 6 certified.
- **Bugs fixed in `chunk4 project`** (tests added; 193 pass): it counted the failed Oct 18 launch's 131 `pilot_qwen` rows (now only rows since `gepa_launch.started`); reflections per run were scaled linearly (about 15); now `reflections_per_run` follows GEPA's call accounting (seed val pass 70, then 6 calls per iteration plus 70 per accepted child; pilot: 70 + 3 x 6 + 70 = 158). Reflection time and cost are their own terms in the overnight and cost projections.
- **Numbers** (from `runs/chunk4/block2_numbers.json`, script `runs/chunk4/block2_numbers.py`, from `summary.json`; subagent check: pending, at the freeze):
  - Go: Qwen3-8B truth-faithful 6.7% (no); reference judge 19/20 (yes); exact matches 0.0% (yes); projected total $93.73 upper, $71.07 with parallel GEPA (yes).
  - Reflections per run at 800 calls: 24.9 at the pilot's accept rate (1 of 3), 9.6 to 121.7 for all to none accepted. Reflection: $0.097 and 121 s median per 3-record call (10 real calls). Six runs: $14.47 expected ($5.58 to $70.72).
  - Overnight (chunk 5): 4.33 h = GEPA 1.45 h in parallel + final eval 2.74 h + setup 0.14 h; GEPA serial upper bound 7.13 h.
- Drafted, not applied: `runs/chunk4/prereg_go1_draft.md` (go criterion 1 not met, proceeding because...).
- **Cost:** $0.66 this entry (arm F tests); chunk 4 $10.92, total $10.95.

### 2026-10-22 · chunk 4 · pod 5: GEPA pilot run and chunk 5 dry run, both done

- **Pod 4** (00:40 UTC): setup started, then Neel stopped the run for a new pod; it went unreachable before I could stop it. Nothing ran or pushed. The laptop load check started with it froze when the laptop slept (1 of 6 calls returned, $0.05); discarded.
- **Pod 5** (H100 80GB HBM3), queue `scripts/chunk4_pod_queue.sh`: setup 02:32 to 02:42 UTC, both servers healthy; gate open.
- **Run pilot_qwen** (02:42 to 02:49 UTC): Qwen3-8B, thinking off, arm A seed plus few-shot, 150 metric-call budget. Outcome: done, exit 0, 158 metric calls, 3 reflections (95 s, 164 s, 78 s), 0 failed API calls. Val: seed best at 5.7% (4/70); one candidate accepted on its minibatch scored 2.9% (2/70). API $0.26, metered GPU $0.44. Commit 66a2b28.
- **Run chunk5_dryrun** (02:49 to 02:54 UTC): B_s0 and D_s0 at 10 metric calls on 5 val items, exit 0 each; sanity check no problems; final eval of all 6 arms on 5 train stand-ins, every finish reason stop. Arm F (Kimi-K3): 5 of 5 under the 16,384 cap (778 to 5,470 output tokens), 15 to 107 s each. API $0.31, metered GPU $0.17. The pod stopped itself. Commit 00289c9.
- **Load check** (`reflect_load`, laptop, 02:32 UTC, during setup): 6 concurrent 3-record Kimi-K3 reflections, 6 of 6 pass, 234 s wall, 53 to 234 s per call, one HTTP 429 retried, $0.66 (`runs/chunk4/reflection_load.json`).
- **Block 2, arm F options** (from `runs/chunk4/block2_arm_f_options.json`, script `runs/chunk4/block2_arm_f.py`; 247 test items, 7 observed Kimi-K3 arm F calls, 1 hit the 16k cap):
  - Today (16k, Kimi-K3): about $20.68 expected, $61.18 worst; about 35 items expected cut off.
  - (a) 32k for all arms: arm F about $29.35 expected, $121.89 worst; ReForm-8B hit 16k on 1 of 30 pilot outputs, Qwen3-8B (thinking off) max 230 tokens, so the formalizer arms barely change.
  - (b) 16k, arm F on GLM-5.3 ($1.40 / $4.40 per 1M, third-party price lists): about $6.15 if its token use is like Kimi-K3's, $18.03 worst; untested on our prompts.
  - (c) drop arm F: $0.
  - The prereg budget line for arm F is under $10; only (b) and (c) fit it.
- Merge note: laptop and pod both appended to `runs/costs.jsonl`; merged as a multiset union (781 rows = 489 laptop + 292 pod-only).
- **Cost:** $1.90 this entry ($1.24 API and $0.61 metered GPU on pod 5, $0.05 discarded load check); chunk 4 $10.26, total $10.29.

### 2026-10-22 · chunk 4 · pilot gate narrowed (Neel); reflection load check added

- **Did:** Neel's change of plan. The pod's gate (`chunk4 preflight_ok`) now needs only the 3-record reflection and the 4 judge checks (`GATE_CHECKS`). Reason (Neel): GEPA reflects on minibatches of 3, so a 15-record reflection never happens in a run; GEPA never calls arm F. Both checks still run and are reported. On the 00:21 UTC preflight the gate reads open.
- Reflection limit for the pilot: already 600 s per attempt, 1 retry (`llm.purpose_limits.reflection`); no config change. Arm F and `generation.max_tokens` unchanged (Neel).
- New step `chunk4 reflect_load`: 6 concurrent live 3-record reflections on different pilot minibatches (chunk 5's load), information only, written to `runs/chunk4/reflection_load.json`; it never touches the gate file. Tests: 190 pass.

### 2026-10-22 · chunk 4 · full preflight rerun, 600 s cap: failed (5 of 7)

- **Did:** new preflight flag `--cap S` (every per-attempt timeout at most S seconds, preflight only; `config.yaml` unchanged). Fixed `--once`: it now also zeroes the per-purpose retries (reflection kept 1). Test added; 189 tests pass.
- **Run** `preflight --fresh --cap 600`, 00:03 to 00:22 UTC, laptop, run id `preflight`. Log `runs/chunk4/preflight_2026-10-21/attempt3_full_cap600_0003.log`. Numbers from `runs/chunk4/api_preflight.json`:
  - reflection_minibatch_3 (Kimi-K3): pass, 101 s, 971 in / 5,038 out tokens, $0.08
  - reflection_long_15 (Kimi-K3): fail, HTTP 503 "Service unavailable" on both attempts (00:10 after 340 s, 00:16), 685 s total
  - arm_f_generate (Kimi-K3, pnv_004): fail, 315 s, 645 in / 16,384 out tokens, all reasoning, finish length, no Lean statement, $0.25 (Oct 18: 6,849 out tokens, pass)
  - opt and ref judges on pnv_258 and pnv_260: all 4 pass, 0 to 7 s each
  - Gate (`chunk4 preflight_ok`): closed. The Oct 18 results are archived as `runs/chunk4/api_preflight_2026-10-18.json`.
- **Cost:** $0.33 this entry, chunk 4 $8.36, total $8.39.
- **Waiting on Neel:** Kimi-K3 decision. Two separate problems: the long reflection is not being served (503), and arm F now runs past `generation.max_tokens` 16,384 (raising it would change a setting the prereg holds identical across arms).

### 2026-10-21 · chunk 4 · cut scope; live API preflight failed (Kimi-K3 slow, then 503)

- **Did** (Neel's cut-scope list, all pushed):
  - Every GEPA candidate's full-val outputs are saved to `runs/<run_id>/candidates/` (raw output, extracted Lean, compile result, judge verdict). A test shows GEPA's code path cannot reach a truth score.
  - `scripts/chunk5_job.py`: the chunk 5 combined job (six GEPA runs in parallel under one GPU meter, sanity check, final eval). Its `--dry-run` uses 2 runs of about 10 metric calls on 5 val items under `runs/dryrun_chunk5/`, then a final eval on 5 train items standing in for test and miniF2F. Tests show the dry run never loads a held-out item.
  - The failed Oct 18 pilot run moved to `runs/pilot_qwen_failed_2026-10-18` (its saved GEPA state would have been resumed); `chunk4 gepa` refuses a run dir with DONE or STOPPED.
  - Analysis additions coded and tested: truth-label sources per arm, reference-judge false positives and negatives, compile/meaning split of truth gains. Prereg text drafted, not applied: `runs/chunk4/prereg_analysis_additions_draft.md`.
  - CLAUDE.md: the standing post-freeze scope rule. Three parked ideas added to the Now box.
  - Labeling page rebuilt to Neel's spec (`~/Desktop/chunk4_labeling.html`; old page kept as `chunk4_labeling_2026-10-18.html`); same items, glosses, blinding, storage key and `labels.csv` format; records saved to `runs/chunk4/label_records.json`.
  - Every API call (judges, reflection, formalizers, arm F, AXLE) now has a hard wall-clock limit per attempt and a retry cap: judges 300 s and 4 retries; formalizer outputs 1800 s and 1; reflection 600 s and 1 (Neel's cap); AXLE 600 s per attempt, then an outage. Exhausted retries stop a GEPA run with STOPPED and the reason; the chunk 5 job records a final-eval failure and exits non-zero. Tests with mocked hanging calls. Cost rows now carry `seconds`; every failed attempt goes to `runs/api_failures.jsonl`.
  - `scripts/chunk4_pod_queue.sh`: setup, then a gate (`chunk4 preflight_ok`: all 7 preflight checks passed, under 24 h old; closed means no GEPA and the pod stops), then the GEPA pilot run, then the chunk 5 dry run, then the pod stops.
  - Go/no-go additions for the pilot report: reflection latency (median, slowest), timed-out and failed calls, projected overnight run time including expected hang stall.
- **Preflight today** (logs in `runs/chunk4/preflight_2026-10-21/`; cost rows `run_id: preflight`):
  - 20:32 run: stopped by me at 20:47; the 300 s client timeout made the long Kimi-K3 call time out and retry.
  - 20:48 run (fresh cache, 1800 s timeout): short reflection (3 records) passed, 971 in / 8,109 out tokens, $0.12, about 2.5 min. Long reflection (15 records): no reply in 29 min; killed at 21:20 (Neel's 2:20pm rule).
  - 21:20 rerun (single attempt, no retries): the long reflection and then arm F both got HTTP 503 "Service unavailable" from Together for Kimi-K3 (arm F at 21:31:46). The judges did not run. A preflight bug made the arm F error crash the script instead of recording a failed check; fixed (API errors are now failed checks), with a test.
  - Result: preflight failed. Per Neel's rule, no GEPA; no pod was running.
- **Cost:** $0.23 today (two Kimi-K3 reflection replies); failed attempts are not billed rows. Chunk 4 $8.03, total $8.06.

### 2026-10-18 · chunk 4 · Kimi-K3 chosen, live API preflight

- **Did:** Neel chose `moonshotai/Kimi-K3` for reflection and arm F ($3 / $15 per 1M tokens; fallback `zai-org/GLM-5.3` if the projection goes over). New step `chunk4 preflight`: live calls from the laptop, each required to add a paid cost row (no cache hits). Reflection uses GEPA 0.1.4's own prompt renderer with our feedback records from real few-shot pilot rows.
- **Numbers** (from `runs/chunk4/api_preflight.json`):
  - Reflection, 3 records: pass, 67 s, 971 in / 4,693 out tokens, $0.07, finish stop
  - Reflection, 15 records: first attempt failed (finish length at the 8,000-token cap, no instruction); with a 32,000-token cap: pass, 260 s, 3,611 in / 24,240 out, $0.37
  - Arm F (train item pnv_004, arm A prompt + few-shot): pass, 80 s, 645 in / 6,849 out, $0.10, the statement compiles
  - Optimization judge (gpt-oss-120b) and reference judge (DeepSeek-V4.1-Flash), 2 compiled pilot outputs each: pass, parsed verdicts
- **Changes:** `gepa.reflection_max_tokens` 8000 to 32000. A reflection reply cut off at max_tokens now stops the GEPA run (like a failed call) instead of becoming a candidate. New tests for both and for the preflight pass rules.
- **Cost:** $0.76 this entry, chunk 4 $7.80, total $7.83.
- **Next:** a pod for the GEPA pilot run.

### 2026-10-18 · chunk 4 · few-shot rerun, labeling page, GEPA pilot run failed (reflection model down)

- **Did:**
  - Neel's last arm A change before the freeze: the syntax block removed from arms A and E; a fixed few-shot block (`prompts/fewshot.txt`) of 3 train examples, each laid out like a real query (English, its context block, the answer). Drawn with seed 0 from the 43 train items without helpers whose reference compiles with autoImplicit off: pnv_218, pnv_226, pnv_018. Attached by config to arms A, E, F and the B and pilot GEPA runs; GEPA edits the instruction text only, and every GEPA run (B and D) trains on the other 47 train items (commit fbbdd38). Prereg change drafted, not applied (`runs/chunk4/prereg_fewshot_draft.md`).
  - Neel's dated predictions for the false-positive Q3 (commit 03c80a8).
  - Fourth pod (fresh deploy, H100 80GB HBM3, $3.99/hr). Setup with the servers started one after the other: both healthy, 16.15 GiB KV cache each.
- **Run pilot_a3** (2026-10-18, pod, val only): Qwen3-8B, thinking off, arm A's instruction line plus the few-shot block, same 30 pilot items, `generation` unchanged. Outcome: complete. Output `runs/chunk4/pilot_a3.jsonl.gz`.
- **Numbers** (from `runs/chunk4/summary.json`, steps `stats`, `diagnose`, `costs`; subagent check: pending, with the labels and GEPA numbers):

  | Qwen3-8B, thinking off | First arm A | Syntax block | Few-shot seed |
  | --- | --- | --- | --- |
  | Compile | 16.7% (5/30) | 10.0% (3/30) | 20.0% (6/30) |
  | Truth faithful | 6.7% (2/30) | 3.3% (1/30) | 6.7% (2/30) |
  | Judge score | 6.7% (2/30) | 0.0% (0/30) | 6.7% (2/30) |
  | Certified | 1 | 1 | 0 |
  | Exact matches | 0.0% | 0.0% | 0.0% |
  | Tokens mean / max | 93 / 175 | 94 / 230 | 66 / 133 |

  - Few-shot compile failures (24), first Lean error: unknown identifier 8, unexpected or expected token 6, type expected 4, the rest type and instance errors. Lean 3 habits or `variable` lines in 3 of 24 (9 of 27 with the syntax block). No output reused an example's theorem name.
  - 108 tokens/s at 16 workers (shorter outputs); setup 0.14 h.
- **Labeling page:** 20 compiled outputs on distinct items, 10 ReForm-8B and 10 Qwen3-8B (6 few-shot, 3 syntax block, 1 first run), glosses for all 40 statements; copied to `~/Desktop/chunk4_labeling.html`. No arm or model name on the page.
- **Run pilot_qwen** (2026-10-18 21:28 to 21:31 UTC, pod, via `run_job.sh`): GEPA 0.1.4, Qwen3-8B thinking off, seed arm A + few-shot, 150 metric calls, seed 0, 47 train / 70 val, reflection `moonshotai/Kimi-K2.6`. Outcome: **failed, discarded.** All 27 reflection calls returned HTTP 400 "No deployments are ready to serve this endpoint" (Together no longer serves Kimi-K2.6 serverless). GEPA caught each error and went on, so the run used 151 metric calls on the seed alone (val score 0.043, 3 of 70), produced 1 candidate, and our runner wrote DONE. Results pushed (commit 8b4c1ee), pod stopped by the job.
- **Bugs found and fixed:**
  - The runner marked a GEPA run DONE although every reflection call failed. A reflection error that survives the client's retries now stops the run with a STOPPED marker (no DONE, no best prompt), like an AXLE outage; a rerun resumes from GEPA's state. New test.
  - My first chunk 4 plan had a live smoke call to the reflection model and arm F's model before any GPU time. I never ran it; it would have caught Kimi-K2.6 being down.
- **Probe of reflection candidates** (Together, 8 output tokens each): live: `moonshotai/Kimi-K3` ($3 / $15 per 1M tokens in / out), `zai-org/GLM-5.3` ($1.40 / $4.40), `MiniMaxAI/MiniMax-M3` ($0.30 / $1.20). Not serverless: `moonshotai/Kimi-K2.6` (the placeholder for reflection and arm F), `moonshotai/Kimi-K2.5-fp4`, `nvidia/nemotron-3-ultra-550b-a55b`.
- **Cost:** $1.22 this entry (GPU $1.19, gloss $0.02, judges and probes under $0.01), chunk 4 $7.04, total $7.07.
- **Next:** labels; Neel picks the reflection model (and arm F's); GEPA pilot rerun on a new pod.

### 2026-10-18 · chunk 4 · rerun with the Lean 4 syntax block, stopped at the go check again

- **Did:**
  - Neel's decisions before the freeze: thinking mode off. Neel's Lean 4 syntax block added verbatim to the top of `prompts/arm_A.txt` and `prompts/arm_E.txt` (diff checked by Neel; commit f5faca3); arm C unchanged.
  - Analysis: Q3 is now the judge false-positive rate among compiled outputs (judge faithful, truth unfaithful, divided by compiled), GEPA arm minus seed arm, paired bootstrap, same decision rule. Per GEPA seed the rate is a ratio of sums over items, then the mean over seeds. Judge gain minus truth gain stays as a descriptive number with no decision rule. Hand-check Q3 uses hand labels. 5 new tests. The prereg change is drafted, not applied: `runs/chunk4/prereg_q3_draft.md` (commit 8e28fe9).
  - Second pod session on a new pod (Neel started it; H100 80GB HBM3, $3.99/hr, again no separate volume). Ran `chunk4 rerun`, then paused the pod (`runpodctl stop`, never remove: Neel's rule) at 20:31:49 UTC.
- **Run pilot_a2** (2026-10-18, pod, val only): Qwen3-8B, thinking off, `prompts/arm_A.txt` with the syntax block (sha256 5479558c048d...), the same 30 pilot items, `generation` config unchanged (temperature 0.6, 1 sample, 16,384 max tokens, seed 0). Outcome: complete. Output `runs/chunk4/pilot_a2.jsonl.gz`; the first run's `pilot.jsonl.gz` is unchanged.
- **Numbers** (from `runs/chunk4/summary.json`, steps `stats`, `diagnose`, `costs`; subagent check: match on every count, rate and cost, its numbers in `runs/chunk4/subagent_check_rerun.json`; every invariant holds, and the 30 item ids equal the first run's):

  | Qwen3-8B, thinking off | First arm A | Arm A with syntax block |
  | --- | --- | --- |
  | Compile | 16.7% (5/30) | 10.0% (3/30) |
  | Truth faithful | 6.7% (2/30) | 3.3% (1/30) |
  | Judge score | 6.7% (2/30) | 0.0% (0/30) |
  | Certified | 1 | 1 |
  | Exact matches | 0.0% | 0.0% |
  | Tokens mean / median / max | 93 / 86 / 175 | 94 / 88 / 230 |

  - The 30 outputs all differ from the first run. Compiled items: first run pnv_097, pnv_112, pnv_169, pnv_285, pnv_305; rerun pnv_034, pnv_112, pnv_160.
  - Rerun compile failures (27), first Lean error: unknown identifier 11, expected or unexpected token 10, the rest type, instance and field errors. Lean 3 habits or `variable` lines in 9 of 27 (`variable` lines 4, Lean 3 lambda 3, snake_case 1, norm bars 1, old binder 0). Example: `∃ λ : k, ...` uses `λ` as a variable name, which Lean 4 rejects.
  - Of the 3 compiled rerun outputs, pnv_160 is certified faithful (reference judge also faithful) but the optimization judge said unfaithful, so the judge score is 0 of 30 while truth is 1 of 30 (found by the subagent check).
  - Go check: Qwen3-8B truth faithful at least about 10%: no (3.3%). Exact matches under 20%: yes (0.0%).
  - 181 then 186 tokens/s at 16 workers for thinking off (first run, rerun).
  - Pod session 2: container up 19:52:05 to 20:31:49 UTC, 0.66 GPU hours, setup 0.51 h (including the failed start below).
- **Bugs found and fixed:**
  - Both vLLM servers starting at once each sized their KV cache while the other was loading, and both failed ("Available KV cache memory: -1.61 GiB"). `setup_pod.sh` now starts ReForm-8B only after Qwen3-8B is healthy. Session 1 never hit this because ReForm-8B's port clash delayed its start.
  - The new pod's id differs from `RUNPOD_POD_ID` in `.env`, so `run_job.sh` would have stopped the old pod. It now takes the id from the container (`/proc/1/environ`), with `.env` as the fallback.
  - `gpu_balance` subtracted every chunk 4 GPU hour ever logged, which would undercount a second session. It now counts only rows logged after the current session's container start; each session is recorded in `summary.json` `pod_sessions`.
  - My status at 20:12 UTC said the servers were loading; they had failed at 19:59. I had read 0 MiB of GPU memory as loading without checking the server logs.
- **Cost:** $2.64 this entry (GPU $2.64, judges under $0.01), chunk 4 $5.82, total $5.85.
- **Waiting on Neel:** the go check fails again (1 of 30; the line is about 3 of 30). The syntax block fixed some Lean 3 habits (Mathlib 4 class names such as `Field` and `AddCommGroup`, no old binder), but compile failures are mostly unknown identifiers and parse errors, which point to Mathlib name knowledge rather than syntax. Both reruns are 30 items, so 2 vs 1 is within noise.

### 2026-10-18 · chunk 4 · pilot stopped at the go check

- **Did:**
  - prereg.md and CHUNKS.md edits from Neel's answers to the chunk 3 questions (Neel checked the diff; commit fe17ebb): Changes item 13 (the random part of the hand-check is one set of test items labeled in all four core arms, paired bootstrap), the matching Scoring, Analysis plan and chunk 6 text, and the decision rule ("at least 5 points in size, in either direction, with the sign reported"). `src/analysis.py` `hand_check` now runs Q1 to Q3 on the random part through the same paired bootstrap; 4 new tests. Arm A's seed prompt stays as written (Neel).
  - Hosting: the pod is an H100 SXM 80GB (`nvidia-smi`: H100 80GB HBM3) at $3.99/hr; PCIe and NVL were out of capacity. `config.yaml` `gpu.type` and `gpu.usd_per_hour: 3.99`. The pod has no separate volume: `/workspace` is the 50 GB container disk, so caches are lost when it stops.
  - Built `scripts/chunk4.py` (steps gen, armf, label, gepa, gpu, agree, project, stats, diagnose, costs) and `tests/test_chunk4.py` (9 tests). The pilot GEPA run (`pilot_qwen`, 150 metric calls) lives under `pilot:` in config, outside `gepa.runs`, so chunk 5 and the firewall never see it.
  - Pilot steps 1 to 3 (prereg "Pilot and go criteria"): pod setup, 30 seeded val items in three configurations, judge score, truth score and memorization check on all 90 outputs. Then stopped the pod (18:50:09 UTC) under the go-check stop rule.
- **Run pilot_gen** (2026-10-18, pod, val only): config `generation` (temperature 0.6, 1 sample, 16,384 max tokens, seed 0, 16 workers), prompts `prompts/arm_A.txt` (Qwen3-8B) and `prompts/arm_C.txt` (ReForm-8B). Outcome: complete on the second attempt (the first stopped at ReForm-8B, see Bugs). Output `runs/chunk4/pilot.jsonl.gz`.
- **Numbers** (from `runs/chunk4/summary.json`, steps `stats`, `diagnose`, `costs`; subagent check: match on every count and rate, its numbers in `runs/chunk4/subagent_check.json`; every invariant holds: judge score and truth faithful never exceed compiled, all 90 rows are val items, the same 30 items per configuration):
  - qwen_nothink: compile 16.7% (30 outputs), format failures 0, truth faithful 6.7%, judge score 6.7%, certified 1, exact matches 0.0%, tokens mean 93 / median 86 / max 175, hit 16,384 cap 0, 181 tokens/s and 0.52 s per item at 16 workers, API $0.0004 per output
  - qwen_think: compile 3.3% (30 outputs), format failures 0, truth faithful 0.0%, judge score 0.0%, certified 0, exact matches 0.0%, tokens mean 2980 / median 2672 / max 6861, hit 16,384 cap 0, 1313 tokens/s and 2.27 s per item at 16 workers, API $0.0000 per output
  - reform: compile 63.3% (30 outputs), format failures 1, truth faithful 46.7%, judge score 53.3%, certified 8, exact matches 0.0%, tokens mean 1786 / median 1037 / max 16384, hit 16,384 cap 1, 419 tokens/s and 4.26 s per item at 16 workers, API $0.0015 per output
  - Qwen3-8B compile failures, first Lean error: unknown identifier 11 of 25 (thinking off) and 12 of 29 (thinking on), unexpected token 7 and 6, the rest type and instance errors. Lean 3 habits (`λ x,`, `at_top`, `is_...` names, `∥x∥`, `∑ x in s`) or `variable` lines appear in 8 of 25 and 7 of 29 failures.
  - Go checks so far: Qwen3-8B truth faithful in 10% to 70%: no (6.7% thinking off, 0.0% thinking on). Exact matches under 20%: yes (0.0% in every configuration). Reference judge agreement and projected total: not measured (no labels, no GEPA pilot run).
  - Pod: container up 18:03:20 to 18:50:09 UTC, 0.78 GPU hours; setup took 0.18 h after the venv was created.
- **Bugs found and fixed:**
  - The pod image's system Python refuses pip installs (PEP 668): setup now installs into `/workspace/venv`, and `run_job.sh` puts it on PATH.
  - vLLM 0.30.0 cannot install with our `numpy==2.5.4` pin: on the pod, vLLM's numpy wins. The analysis runs on the laptop with the pinned version.
  - RunPod's nginx proxy listens on port 8001, so ReForm-8B's server failed to bind and the old health check accepted Qwen3-8B's reply through the proxy. ReForm-8B now serves on 8010, and setup checks each port's served model name.
  - `runpodctl` needs `RUNPOD_API_KEY`, which exists only in the container's PID 1 environment. `run_job.sh` would have pushed results and then failed to stop the pod; it now reads the key from `/proc/1/environ`. Found when stopping this pod.
  - A rerun of `gen` would time cached generations at about 0 s: each configuration is now timed once and saved; the two Qwen3-8B timings come from the first attempt's log (`runs/chunk4/gen_attempt1.log`).
- **Choices the spec left open:**
  - Truth score on all 90 pilot outputs, not only the 20 to be labeled: the go check needs Qwen3-8B's rate on the pilot items, and it cost about $0.06.
  - Pod GPU cost = container wall clock times $3.99/hr, logged as balancing `gpu` rows (`run_id: pod_session`). RunPod may also bill a few minutes before the container starts.
- **Parked:** extraction keeps only the theorem, so a Qwen3-8B answer that declares `variable` lines (3 of 25 failures, thinking off) loses those binders. The task asks for one theorem, so this is per spec.
- **Waiting on Neel:** the go check fails on Qwen3-8B's truth rate (2 of 30 thinking off; the line is about 3 of 30). Options:
  1. Finish the pilot anyway (label 20, GEPA pilot run), then decide. It shows whether GEPA moves Qwen3-8B off the floor. Restart overhead is about 25 min of setup (the pod has no volume).
  2. Accept 2 of 30 as within "roughly 10%" and go on with thinking off.
  3. Change the design before the freeze, for example arm A's seed naming Lean 4 Mathlib syntax (it is also B's seed), or another general model on the same base.
  4. Take it to a project chat first (the chunk 4 rule for a failed go check).
- **Cost:** $3.17 this entry (GPU $3.11, reference judge $0.05, optimization judge $0.01), $3.20 total. The cost log has 27 optimization-judge and 28 reference-judge rows for 25 judged outputs; probably the one re-ask for replies without valid JSON (not checked).
- **Next:** Neel's decision, then "Continue chunk 4"

### 2026-10-18 · before chunk 4 · arm E prompt and predictions

- **Did:** saved arm E's prompt to `prompts/arm_E.txt` (drafted by Claude, edited by Neel; two lines damaged in pasting were replaced with Neel's exact text after he reviewed the whole file). In prereg.md: arm E's row now says "Drafted by Claude from the task description and edited by Neel, before any GEPA output exists."; Neel's predictions filled in and dated 2026-10-18, with his note on what the confidence numbers mean. Both are fixed before the pilot's short GEPA run (prereg Changes, item 6).
- **Cost:** $0 this entry
- **Next:** chunk 4, once the pod and `.env` entries are in

### 2026-10-18 · chunk 3 · runner

- **Did:** prereg.md Changes items 11 and 12, arm C row and the disagreement-count bullet (approved by Neel; commit c218f54). Rebuilt certificates as one Lean file per direction that declares only the hypothesis-side theorem (Neel's check); the candidate side has autoImplicit off and the reference side is as shipped. Built the generation client (`src/generate.py`, `src/prompting.py`), the data firewall (`src/data/firewall.py`), the GEPA adapter and runner (`src/gepa_adapter.py`, `src/runner.py`, `scripts/gepa_run.py`, gepa 0.1.4 with library defaults), GPU cost meter (`src/costs.py`), final eval (`src/final_eval.py`, `scripts/final_eval.py`), the analysis (`src/analysis.py`, `scripts/analyze.py`), pod scripts (`scripts/setup_pod.sh`, `scripts/run_job.sh`, both with `--dry-run`), mocks (`src/mocks.py`) and `scripts/chunk3.py`. Tests: 123 pass.
- **Numbers** (from `runs/chunk3/summary.json` and `runs/chunk2/summary.json`; subagent check: match on every count and point estimate, intervals within 0.5 points, its numbers in `runs/chunk3/subagent_check.json`):
  - Golden cases with the new certificate builder: 15/15 pass (one new case: pnv_280 with `f_a` bound explicitly, certified).
  - autoImplicit / option references (hand-written candidate binds the auto-bound name):
    - pnv_025 (Axler_exercise_7_6, test): candidate compiles with autoImplicit off: True; certified: True; reference judge: None
    - pnv_207 (Axler_exercise_6_13, test): candidate compiles with autoImplicit off: True; certified: True; reference judge: None
    - pnv_208 (Axler_exercise_7_5, val): candidate compiles with autoImplicit off: True; certified: True; reference judge: faithful
    - pnv_280 (Ireland_Rosen_exercise_2_4, train): candidate compiles with autoImplicit off: True; certified: True; reference judge: faithful
    - pnv_092 (Herstein_exercise_5_3_10, val): candidate compiles with autoImplicit off: True; certified: True; reference judge: faithful
  - Smoke call (Qwen/Qwen3.5-9B, pnv_075): finish stop, compiled True, judge score 1, truth faithful
  - Dry run on mocks:
    - B_s0: done, 152 metric calls, best val 1.000
    - B_s1: done, 152 metric calls, best val 1.000
    - B_s2: done, 152 metric calls, best val 1.000
    - D_s0: done, 152 metric calls, best val 1.000
    - D_s1: done, 152 metric calls, best val 1.000
    - D_s2: done, 152 metric calls, best val 1.000
    - final rows per arm: {'A': 490, 'B': 1470, 'C': 490, 'D': 1470, 'F': 247}; figures: ['judge_vs_truth_gain.png', 'truth_by_arm.png']
    - Q1: 58.7 [52.6, 64.8] effect
    - Q2: 0.0 [0.0, 0.0] no meaningful effect
    - Q3_qwen3-8b: 0.0 [0.0, 0.0] no meaningful effect
    - Q3_reform-8b: 0.0 [0.0, 0.0] no meaningful effect
  - Chunk 3 cost: $0.0014; by purpose: ref_judge 3 calls $0.0011, generate 1 calls $0.0000, opt_judge 1 calls $0.0002
- **Bugs found and fixed:**
  - pnv_092 (val) starts with `set_option maxRecDepth 2048 in`; normalization returned nothing for it, so its truth score and certificate would have crashed. Normalization, extraction and certificates now keep leading `set_option ... in` lines. A test checks that all 367 references normalize.
  - Cache writes used one temp file name per process, so two threads checking the same Lean file collided. Temp names are now unique.
- **Choices the spec left open:**
  - User message for every arm: instructions, the English, then one fixed block with the header and helpers (Neel chose this). Arm A's seed (`prompts/arm_A.txt`): "Translate the following math problem into a single Lean 4 theorem statement using Mathlib. End the statement with `:= by sorry`. Put the final statement in a ```lean4 code block." Arm F uses the same seed. Neel may want to edit arm A's wording before the freeze.
  - Certificate tactics: `exact @H`, `intros; apply H <;> assumption`, `intros; simp_all [H]`, `intros; aesop (add unsafe 50% apply H)`, `intros; have hcert := @H; tauto`; the removal check swaps `H` for `cert_true : True`. An attempt counts as proved when no Lean error falls inside its own lines.
  - The generation seed is the same for all three GEPA seeds, so the three runs share cached generations for the same prompt and item; they differ through GEPA's own seed.
  - GEPA checks its budget between iterations, so a run can overshoot by at most one iteration (dry run: 152 metric calls for a budget of 150).
  - An AXLE outage during GEPA stops the run (marker `STOPPED`, no `DONE`); rerunning resumes from `runs/<run_id>/gepa`.
  - Analysis: items with any exact memorization match in a core arm are dropped for the "without exact matches" contrasts; the reference judge's agreement with hand labels uses compiled items only (it runs only on those).
  - Placeholders until the pilot: reflection model and arm F `moonshotai/Kimi-K2.6`; generation temperature 0.6, 1 sample, 16,384 max tokens; GEPA budget 800. vLLM pinned at 0.30.0 (2026-09-22), 0.45 of GPU memory per server.
  - The smoke call used `Qwen/Qwen3.5-9B` on Together because Qwen3-8B is not served there.
- **Questions for Neel before the freeze (not blocking):**
  - Decision rule: "the estimate is at least 5 points" is read as |estimate| >= 5, and the sign is reported, so a GEPA prompt that hurts by 5 or more with an interval below 0 is also an "effect".
  - "Q1 to Q3 on the random part of the hand-labeled sample": the random sample is stratified by arm, so items are not paired across arms. The script compares per-arm rates with an unpaired bootstrap within each arm.
- **Note for chunk 5:** `run_job.sh` stops the pod when its job ends, so the six GEPA runs and the final eval must be started as one job (one command that runs all six in parallel, the sanity check, then the final eval), not six separate jobs.
- **Cost:** $0.0014 this entry (smoke call and reference-judge checks), $0.0336 total. The golden re-run's one new judge pair was logged under chunk 2 by the chunk 2 script.
- **Problems:** none open. The dry run fed test and miniF2F item text to the mock formalizer and mock judge (copies of references, no model); no model saw a test item.
- **Next:** chunk 4 (pilot and freeze, GPU)

### 2026-10-18 · chunk 2 · scoring

- **Did:** prereg.md edits approved by Neel (Changes items 7, 8, 10 plus consistency fixes; commit e9eeb8a). Wrote `.claude/settings.json` (Neel approved). Re-ran the miniF2F load with the scripted `∑/∏ x in s` binder rewrite. Built `src/scoring/`: extraction, our comment stripper, normalization, compile with `set_option autoImplicit false in`, Together client with cache, cost log and budget stop (`src/llm.py`), both judges, equivalence certificates, truth score, memorization check, labeling page. AXLE wrapper gained `normalize`. Entry script `scripts/chunk2.py`. Tests: 86 pass (golden and AXLE tests run live against the cache).
- **Numbers** (from `runs/chunk1/summary.json` and `runs/chunk2/summary.json`; subagent check: match on every count, its numbers in `runs/chunk2/subagent_check.json`):
  - miniF2F after the binder rewrite: 243 usable, 1 dropped of 244. The rewrite applied to 31 items, all of them the ones that failed in chunk 1, and 31 now compile. Still failing: minif2f_amc12a_2020_p15 (lean.unknownIdentifier): Unknown constant `Complex.abs`
).
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
- **Choices the spec left open:**
  - Stripper: ours. AXLE's `remove_comments` treats `'` as a string quote, so after a single primed name (`x'`) it keeps a trailing comment, exactly the injection the stripper exists to stop.
  - Docstrings are removed by our stripper directly; AXLE `normalize_doc_comments` is used only in the memorization check. After extracting one declaration there is no docstring left for normalize to convert.
  - Memorization key: AXLE `normalize` (its defaults plus `normalize_doc_comments`), no comments, fixed name, `:= by sorry`, all whitespace removed (so `x*y` matches `x * y`). The original ProofNet is Lean 3 only and skipped; its two Lean 4 ports from ProofNet-Verified's repo are used. 14 rows in each port are `instance` declarations, not theorems, and get no key.
  - Certificates: tactics `exact hcert`, `simpa using hcert`, `intros; simp_all`, `intros; aesop`, `intros; tauto`; the no-hypothesis run replaces `hcert` with `(hcert : True)` so a tactic that ignores `hcert` cannot pass the check by an unknown-name error. `Type*` becomes one shared `Type u`. Certificates passed every golden case in well under the 3-hour timebox, so `certificates: true`.
  - Judges (placeholders until the pilot): optimization `openai/gpt-oss-120b`, reference `deepseek-ai/DeepSeek-V4.1-Flash`. Gloss model `zai-org/GLM-5.3-Flash`: Llama-4-Scout, Mistral-Small, Ministral, Gemma-4 and gpt-oss-20b are not serverless on Together. GLM thinks even when asked not to, so glosses get 8000 tokens and one retry.
  - A judge reply without valid JSON gets one re-ask, then counts as `unparseable` (not faithful).
- **Parked (for Neel, not built):**
  - Certificates prove logical equivalence, so a candidate that adds an always-true conjunct (golden case `"a--b".length = 4`) is certified faithful while both judges say unfaithful ("Adding extra conclusion"). Under the prereg the certificate wins. The chunk 6 hand-check samples these disagreements, but Neel may want a rule before the freeze.
  - 4 references compile only with autoImplicit on (`F` in pnv_025, pnv_207, pnv_208; `f_a` in pnv_280; splits test, test, val, train). A candidate written in the same style fails to compile under Changes item 10.
  - Arm C's prompt in prereg.md is "Think step by step to translate the mathematical problem in natural language to Lean 4"; ReForm's repo (`lean_plugins/generate.py`) uses the same text plus ", and verify the consistency." followed by the problem. Decide before chunk 3 builds the generation client.
- **Cost:** $0.0296 this entry (49 paid calls), $0.0296 total
- **Problems:** the first judge smoke call used Rudin_exercise_1_2 (pnv_149), a **test** item: one optimization-judge and one reference-judge call on a hand-written candidate, $0.0004, no formalizer output and no score kept. Every later dev and golden call used train items only, and the golden runner now refuses non-train items. Two GLM probe calls bypassed the client and were added to `runs/costs.jsonl` by hand from their reported token usage.
- **Next:** chunk 3

### 2026-10-17 · chunk 1 · setup and data

- **Did:** repo skeleton, `config.yaml`, secret scan (`scripts/secret_scan.py`, installed as pre-commit and pre-push hooks by `scripts/install_hooks.sh`), AXLE `check` wrapper (`src/axle_check.py`: disk cache, retries, outages kept apart), ProofNet-Verified and miniF2F loaders, seeded stratified split. Entry script `scripts/chunk1.py`. No old lean-gepa grader, so the wrapper is new. Tests: 27 pass (3 live AXLE).
- **Numbers** (from `runs/chunk1/summary.json`; subagent check: match, its numbers in `runs/chunk1/subagent_check.json`: compiled 367, sizes {'train': 50, 'val': 70, 'test': 247}, miniF2F usable 212, dropped 32, per-textbook table identical):

- ProofNet-Verified reference compile: 367/367 ({'ok': 367})
- Split sizes (seed 0): {'train': 50, 'val': 70, 'test': 247}; kept together: [['pnv_168', 'pnv_351']]

| Textbook | Total | Train | Val | Test |
| --- | --- | --- | --- | --- |
| Artin | 28 | 4 | 5 | 19 |
| Axler | 26 | 3 | 5 | 18 |
| Dummit Foote | 87 | 12 | 17 | 58 |
| Herstein | 47 | 6 | 9 | 32 |
| Ireland Rosen | 21 | 3 | 4 | 14 |
| Munkres | 60 | 8 | 11 | 41 |
| Pugh | 14 | 2 | 3 | 9 |
| Putnam | 12 | 2 | 2 | 8 |
| Rudin | 56 | 8 | 11 | 37 |
| Shakarchi | 16 | 2 | 3 | 11 |

- miniF2F: 212 usable, 32 dropped of 244 ({'ok': 212, 'lean_error': 32})
  - 31 items: "unexpected token 'in'; expected ','\n"
  - 1 items: '(lean.unknownIdentifier): Unknown constant `Comple'

- **Choices the spec left open:**
  - ProofNet-Verified pinned at commit `160414332dc1`, miniF2F at HF revision `5def31834852`. Raw downloads kept in `data/raw/`.
  - Ids are `pnv_<index>` because `name` is not unique: Rudin_exercise_4_8a is listed twice (index 168 and 351, slightly different statements). The split keeps both copies in one split by swapping with a same-textbook item, so counts and strata are unchanged.
  - Per-textbook quotas use largest-remainder rounding; split seed 0 in `config.yaml`.
  - AXLE statuses: ok, lean_error, timeout, resource (failures), outage (AxleIsUnavailable, RateLimited, Internal and Runtime errors after 3 retries with backoff; never cached or scored). Compile pass = AXLE `okay`.
  - miniF2F header = the text before the docstring; reference = the theorem with `sorry` appended. 31 of the 32 drops use the old `∑ x in s` syntax that this Mathlib no longer parses. Not fixed, per the spec.
  - Python 3.12 venv via uv (system Python is 3.14). `.env` lines are indented; the loader tolerates that.
- **Parked (for chunk 2 to consider, not built):**
  - AXLE's Lean environment has `autoImplicit` on: an unknown identifier in a candidate can compile as an auto-bound variable. Chunk 2 may want `set_option autoImplicit false` in the compile check (scoring decision, needs Neel).
  - The `axiom-axle` 1.9.0 Python package ships `axle.remove_comments` (prereg Changes item 7 says AXLE has none). The prereg still calls for our own tested stripper; it could be a cross-check.
- **Cost:** $0 this entry (AXLE only, 611 calls), $0 total
- **Problems:** `.claude/settings.json` not written (see Waiting on Neel).
- **Next:** chunk 2

### 2026-10-17 · chunk 0 · decisions before starting

- **Did:** wrote `CLAUDE.md`, `CHUNKS.md`, `LOG.md` and `prereg.md` in a claude.ai project chat.
- **Decisions:** Claude Code on Neel's laptop owns all code and runs, and the repo is the only source of truth. Both formalizers run on one rented H100 (RunPod) with vLLM; Qwen3-8B moves off Together, which keeps serving the judges. There is no existing GEPA pipeline, so GEPA comes from the open-source `gepa` library (0.1.4) with a custom adapter, built in chunk 3. Changes to the Oct 17 design doc are listed at the top of `prereg.md`.
- **Cost:** $0 this entry, $0 total
- **Next:** chunk 1
