# Humanizer

Paraphrases text one sentence at a time with
`humarin/chatgpt_paraphraser_on_T5_base`. It runs as its own service and shares no
code with `backend/`. The API has no authentication, so never publish its port.

## API

`POST /humanize` with `{"text": "...", "params": {"num_beams": 5}}` returns
`{"text": "...", "sentences_total": 4, "sentences_rewritten": 3}`. `params` is
optional. `text` is limited to 20,000 characters.

`GET /health` returns `{"status": "ok", "device": null, "model_loaded": false}`.
The model loads on the first request that needs it.

Sentences with inline markup, formula characters or fewer than 4 words keep their
wording, as do sentences over the token limit. A rewrite is dropped if it loses a
number or is under half the original's word count.

## Tests

No torch is needed:

```bash
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements-test.txt
.venv/Scripts/python.exe -m pytest tests -q
```

## Enabling it on the platform

Set `HUMANIZER_URL=http://humanizer:8100` for the backend, then run this from
`backend/`:

```bash
docker compose --profile humanizer up -d --build
```

Course outline, content and meta drafts generated on the Celery worker are then
humanized before an admin reviews them.

## Measured speed

Default parameters, 5-beam search, 8 sentences of sample course prose, with
`transformers` 4.46.3 and the model already loaded:

| Hardware | Seconds per sentence |
|---|---|
| RTX 3050 Laptop (4 GB) | 0.83 |
| Laptop CPU | 1.32 |

## Known quality problems

With the default parameters, the guards don't catch rewrites that keep the numbers
but change the meaning. These came from the same sample runs:

| Original | Rewrite |
|---|---|
| Removing items while looping over a list can skip elements. | To skip elements, loop over a list and remove items. |
| A loop repeats a block of code until a condition is met. | A condition is met and then a loop repeats the code until it completes its block. |
| ...most programs treat them as numbers from 1 to 12. | ...the majority of shows depict them as quantities from 1 to 12. |

An admin needs to read every humanized draft before applying it.
