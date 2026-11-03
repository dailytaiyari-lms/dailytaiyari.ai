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
