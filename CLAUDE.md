# GEPA on Lean Formalizers

Neel Dankar's study: does GEPA prompt optimization make Lean 4 formalizers (Qwen3-8B and ReForm-8B) more faithful, and do judge-measured gains overstate real ones? You (Claude Code) write all the code and run everything. Neel checks in between chunks.

## Start of every session

Read these before doing anything else:

1. `LOG.md`, the "Now" box: where things stand.
2. `prereg.md`: the spec. It wins over everything else, including older copies of the design doc.
3. `CHUNKS.md`: the section for the chunk Neel named.

Neel starts a chunk by typing "Start chunk N" (or "Continue chunk N"). Work only on that chunk. First show a short plan: what you'll build, the tests, the expected cost. Once Neel approves, work without stopping to ask, except under the stop rules below.

Do the work yourself in this one session. Use a subagent only for the verification step.

## Scope lock

- Build only what `prereg.md` and the chunk's section of `CHUNKS.md` describe. No extra arms, metrics, analyses, datasets, models or features. Write ideas under "Parked" in `LOG.md` instead.
- Before the freeze (end of chunk 4), only Neel edits `prereg.md`. The one exception: at the freeze, you write in the decisions Neel made in chunk 4, and he checks the diff before the tag. After the freeze it never changes; any deviation goes in its dated Deviations section, approved by Neel.
- Plain Python, JSONL files, one `config.yaml` for every knob, one entry script per chunk in `scripts/`. No new frameworks beyond GEPA and vLLM.
- Prefer short, boring code. If the spec doesn't cover a choice, pick the simplest option and note it in `LOG.md`.
- After the `prereg-frozen` tag, no new analyses, features or pipeline changes unless a bug blocks the run. New ideas from anyone (Neel, Claude, subagents, outside feedback) go to "Parked ideas" in `LOG.md` and are only considered in chunk 7, labeled exploratory. Don't propose new features unprompted; raise only bugs, blockers and decisions Neel has to make.

## Stop rules

Stop, write the problem under "Waiting on Neel" in `LOG.md`, push, and end the session if:

- the same fix has failed twice
- a step would push spending past the chunk's budget cap in `CHUNKS.md`
- a number looks impossible or too good (for example, more items pass the judge than compile)
- `prereg.md` is ambiguous or can't be done as written
- anything would generate or score model outputs on the test split or miniF2F before chunk 5 (chunk 1 loading them and compile-checking their reference statements is fine)

## Tests and numbers

- Write pytest tests with the code, not after. Every module gets tests.
- Every number in `LOG.md` comes from a script that reads raw files and writes a JSON file. Never type a number by hand.
- A chunk is done only when (1) all tests pass and (2) a fresh subagent, given only the raw files and the definitions in `prereg.md`, recomputes the chunk's key numbers with its own code, without reading `src/`. Counts and point estimates must match exactly; bootstrap intervals must agree within 0.5 points. Log both sets of numbers.
- End every chunk by showing 5 random raw examples (input, output, scores) for Neel to eyeball.

## Data rules

- GEPA sees only the 50 train and 70 validation items. No model output is generated or scored on the 247 test items or miniF2F until chunk 5, after every GEPA run has finished; before that, they are only loaded and their reference statements compile-checked (chunk 1). A test enforces that GEPA code can't load them.
- Golden test cases and examples are built from train items only.
- Never show per-arm test scores before Neel finishes his hand-check in chunk 6. Until then, report health checks only (counts, completion, cost).
- Never edit dataset files by hand.

## Runs

- Cache every model, judge and AXLE call on disk, keyed by a hash of its full inputs (model, prompt, item, sampling settings, seed, sample index). Reruns cost nothing and crashes resume where they stopped.
- Log the cost of every paid call. Scripts stop themselves at the chunk's budget cap.
- AXLE outages are retried and never scored as failures. Lean timeouts count as failures and are counted separately.
- Long jobs run on the GPU pod inside tmux and write to `/workspace`. When a job ends, it pushes its results to GitHub and then stops the pod.
- Every run, including failed and discarded ones, gets a dated `LOG.md` entry: run id, config, outcome, cost.

## Secrets

- Keys live only in `.env` (gitignored), on the laptop and on the pod. Never print, log, echo or commit them.
- A secret scan runs before every push.

## Writing

- No em dashes anywhere: code comments, docs, `LOG.md`, the writeup.
- `LOG.md` entries are short and plain, with units on every number.

## End of every session

1. Run all tests.
2. Update the "Now" box in `LOG.md` and add a dated entry.
3. Commit and push.
4. Tell Neel in 3 lines: what's done, what's next, anything waiting on him.
