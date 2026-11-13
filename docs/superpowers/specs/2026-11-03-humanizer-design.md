# Humanizer service: design

Rewrites AI-generated course prose, one sentence at a time, with the
`humarin/chatgpt_paraphraser_on_T5_base` model. It runs as a separate service
so that the Django backend never imports torch or transformers.

## Scope

| Rewritten | Left untouched |
|---|---|
| Note `lead`, `paragraph`, `callout` and `quote` text | Headings, callout titles, quote attributions |
| Note `bullets` and `numbers` items | Code and table blocks |
| Outline: course, subject and chapter `description`, topic `summary` | Names, highlights, objectives, subtitle, refund policy |
| Meta: `description` and `description_blocks` (same block rules as notes) | Quizzes, assignments, coding problems |
| | Mock papers, notebooks, tutor chat |

## Service: `humanizer/`

A top-level folder with no imports from `backend/`.

```
humanizer/
  app.py            FastAPI app
  humanize.py       humanize_text(): split, guard, paraphrase, rejoin
  sentences.py      split_sentences() using pysbd
  guards.py         should_skip() and accept_rewrite()
  paraphraser.py    load model once, paraphrase()
  requirements.txt  torch, transformers (pinned), fastapi, uvicorn, pysbd
  requirements-test.txt  fastapi, httpx, pysbd, pytest (no torch)
  Dockerfile
  README.md
  tests/
```

`paraphraser.py` imports torch and loads the model on first use. Every other
module can be imported without torch.

### API

`GET /health` returns `{"status": "ok", "device": "cuda" | "cpu" | null,
"model_loaded": bool}`. `device` is null until the model has loaded.

`POST /humanize`

```json
{"text": "...", "params": {"num_beams": 5}}
```

`params` is optional and accepts the keyword arguments of `paraphrase()`. The
response is:

```json
{"text": "...", "sentences_total": 4, "sentences_rewritten": 3}
```

`text` has a 20,000-character limit; anything longer returns 422. A failure while
paraphrasing one sentence keeps that sentence's original text and does not fail
the request. If the model cannot load, the endpoint returns 503.

A lock serializes model calls, so the service handles one sentence at a time.

### `paraphrase()`

The defaults are the ones supplied with the request (`num_beams=5`,
`num_beam_groups=5`, `num_return_sequences=1`, `repetition_penalty=10.0`,
`diversity_penalty=3.0`, `no_repeat_ngram_size=2`, `temperature=0.7`,
`max_length=128`). Changes to the supplied code:

- Remove `trust_remote_code=True` from `generate()`.
- Pin `transformers` to the newest version that still runs `num_beam_groups`,
  found by running the model during implementation.
- `temperature` stays as a parameter, but it has no effect without sampling.

### Sentence handling

`humanize_text(text, paraphrase_fn, params)` works as follows:

1. Split on line breaks, then split each line into sentences with `pysbd`, using
   character spans so that the whitespace between sentences survives.
2. For each sentence, keep the original if `should_skip()` is true. Otherwise
   call `paraphrase_fn` with that one sentence, and keep the original if
   `accept_rewrite()` is false.
3. Rejoin using the original whitespace.

`should_skip(sentence, count_tokens)` is true when the sentence:

- contains a backtick or `*` (inline markup the renderer relies on)
- contains a formula marker: `$`, `\`, `=`, `^`, `<`, `>`, `{`, `}`
- has fewer than 4 words (fragments paraphrase badly)
- has more tokens than `max_length` minus 2, including the `paraphrase: ` prefix
  and the end token (it would be truncated)

`accept_rewrite(original, rewrite)` is false when:

- the rewrite is empty
- it has less than 50% of the original's words
- any number in the original is missing from the rewrite

The rule set is deliberately conservative. A kept sentence is always safe; a
wrong rewrite is an error in teaching material.

## Platform hook: `backend/coursegen/humanize.py`

`humanize_draft(kind, draft, *, previous=None, time_budget_s)` walks the draft for
its `kind`, posts each eligible string to the service, and writes the result back.

Rules:

- **Off by default.** With an empty `HUMANIZER_URL`, the function returns the
  draft unchanged and makes no HTTP call.
- **Worker only.** `run_job` and `apply_refinement` gain a `humanize=False`
  keyword. `coursegen/tasks.py` passes `humanize=True`. The inline fallback in
  `views._enqueue` runs on a web request, so it never humanizes. The step runs
  before `_store_result`, so an admin can never open a draft that is still being
  rewritten.
- **Fail open.** A connection error, timeout or non-200 response keeps the
  original text and stops further calls for that job. The job still succeeds.
- **Time budget.** Before each call, compare elapsed time to the budget. Once it
  is spent, the remaining fields stay original.
  `time_budget_s = min(HUMANIZER_TIME_BUDGET_S, 1400 - meter.elapsed_ms / 1000)`,
  which keeps the job inside the task's 1500-second soft limit.
- **Refine.** Strings that already appear in the previous draft are not sent
  again, so an unchanged paragraph is not paraphrased repeatedly.
- **Field limits.** A rewrite longer than the field's normalizer limit keeps the
  original: note text 4000, list item 500, topic summary 800, subject and chapter
  description 1500, outline course description 4000, meta description 6000.
- **Re-render.** After a content draft is walked, recompute `note.html` and
  `note.estimated_time_minutes`. After a meta draft is walked, recompute
  `course.description_html`.
- **Report.** Set `draft['humanizer']` to `{"status": "complete" | "partial" |
  "failed", "sentences_total": n, "sentences_rewritten": n, "fields_skipped": n}`.
  `failed` means the service could not be reached for any field. The frontend
  and the apply step ignore this key. It is also logged.

The client uses `requests`, already a backend dependency, with a per-call read
timeout of `HUMANIZER_READ_TIMEOUT_S`.

### Settings

| Setting | Default |
|---|---|
| `HUMANIZER_URL` | empty (off) |
| `HUMANIZER_TIME_BUDGET_S` | 600 |
| `HUMANIZER_READ_TIMEOUT_S` | 120 |

## Deployment

`backend/docker-compose.yml` gains a `humanizer` service under
`profiles: ["humanizer"]`, built from `../humanizer`. It publishes no ports, like
`piston` and `nbrunner`, because the API has no authentication. A named volume
caches the Hugging Face model. The three settings are added to `&app-env`.

To enable it, set `HUMANIZER_URL=http://humanizer:8100` and run:

```
docker compose --profile humanizer up -d --build
```

Without the profile and the setting, deployments behave exactly as they do today.
GPU access and memory limits on the production host are left to the deployment.

## Testing

- `humanizer/tests/`, using a fake paraphrase function and no torch:
  sentence splitting ("e.g.", "3.14", whitespace preservation), each guard, and
  the API contract including one failed sentence.
- `backend/coursegen/tests_humanize.py`, with HTTP mocked: the walker changes only eligible
  fields for all three draft kinds, HTML is re-rendered, the setting being empty
  means no HTTP call, the service being down keeps the text and the job succeeds,
  the time budget stops calls, refine skips unchanged strings, and the inline path
  does not humanize.
- One manual run of the real model on sample notes, to pin `transformers` and to
  measure seconds per sentence on the local RTX 3050. The result goes in
  `humanizer/README.md`.

## Known limits

- Sentences with inline formatting, formulas or short fragments stay as generated,
  so some notes will change less than others.
- The number guard catches changed numbers. It does not catch other changes in
  meaning, such as a dropped negation, so admin review of the draft still matters.
- Rewrites are not checked for quality beyond the guards. Admin edits to a draft
  are not re-humanized.
