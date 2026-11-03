# Humanizer Service Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rewrite AI-generated course prose one sentence at a time through a standalone paraphrasing service, with an opt-in hook in `coursegen`.

**Architecture:** A new top-level `humanizer/` FastAPI service owns torch, the T5 model, sentence splitting and the safety guards. `backend/coursegen/humanize.py` walks a draft and posts each eligible string to the service over HTTP. The Celery task turns the step on, so web requests never wait on the model.

**Tech Stack:** Python 3.12, FastAPI, pysbd, torch, transformers, pytest; Django, Celery and requests on the backend side.

**Spec:** `docs/superpowers/specs/2026-11-03-humanizer-design.md`

## Global Constraints

- `humanizer/` imports nothing from `backend/`. `backend/` never imports torch or transformers.
- Only `humanizer/paraphraser.py` imports torch or transformers, and only inside its load function.
- With `HUMANIZER_URL` empty, the backend makes no HTTP call and behaves exactly as it does today.
- Any humanizer failure keeps the original text. It must never fail a generation job.
- Model: `humarin/chatgpt_paraphraser_on_T5_base`. Defaults: `num_beams=5`, `num_beam_groups=5`, `num_return_sequences=1`, `repetition_penalty=10.0`, `diversity_penalty=3.0`, `no_repeat_ngram_size=2`, `temperature=0.7`, `max_length=128`.
- `POST /humanize` rejects `text` over 20,000 characters with 422.
- The `humanizer` Compose service publishes no ports.
- Backend Python: `backend/venv/Scripts/python.exe`. Run backend commands from `backend/`, and service commands from `humanizer/`.
- All commands use the Bash tool (POSIX paths).

---

### Task 1: Sentence splitting, guards and `humanize_text`

**Files:**
- Create: `humanizer/conftest.py`
- Create: `humanizer/requirements-test.txt`
- Create: `humanizer/sentences.py`
- Create: `humanizer/guards.py`
- Create: `humanizer/humanize.py`
- Test: `humanizer/tests/test_sentences.py`
- Test: `humanizer/tests/test_guards.py`
- Test: `humanizer/tests/test_humanize.py`

**Interfaces:**
- Produces:
  - `sentences.split_sentences(text: str) -> list[Piece]`, where `Piece` is a `NamedTuple(text: str, is_sentence: bool)` and `''.join(p.text for p in pieces) == text`
  - `guards.should_skip(sentence: str, count_tokens: Callable[[str], int], max_length: int = 128) -> bool`
  - `guards.accept_rewrite(original: str, rewrite: str) -> bool`
  - `humanize.ModelUnavailable(Exception)`
  - `humanize.HumanizeResult`, a `NamedTuple(text: str, sentences_total: int, sentences_rewritten: int)`
  - `humanize.humanize_text(text: str, paraphrase_fn: Callable[..., list[str]], count_tokens: Callable[[str], int], params: dict | None = None) -> HumanizeResult`

- [ ] **Step 1: Set up the test environment**

Create `humanizer/requirements-test.txt`:

```
fastapi>=0.115,<1
httpx>=0.27,<1
pysbd==0.3.4
pytest>=8,<9
```

Create an empty `humanizer/conftest.py`, which puts `humanizer/` on `sys.path` for pytest.

Run:

```bash
cd humanizer && python -m venv .venv && .venv/Scripts/python.exe -m pip install -q -r requirements-test.txt
```

Expected: exits 0. `.venv` is already in the root `.gitignore`.

- [ ] **Step 2: Write the failing tests**

`humanizer/tests/test_sentences.py`:

```python
from sentences import split_sentences


def sentences(text):
    return [p.text for p in split_sentences(text) if p.is_sentence]


def test_splits_simple_sentences():
    assert sentences("One sentence here. Another one there.") == [
        "One sentence here.",
        "Another one there.",
    ]


def test_does_not_split_on_abbreviation_or_decimal():
    text = "Use a tool, e.g. a hammer. Pi is about 3.14 in value."
    assert sentences(text) == ["Use a tool, e.g. a hammer.", "Pi is about 3.14 in value."]


def test_rejoining_pieces_restores_the_exact_text():
    text = "  First one.   Second one.\n\nThird line here.\n"
    assert "".join(p.text for p in split_sentences(text)) == text


def test_line_breaks_always_separate_sentences():
    assert sentences("A line without a stop\nAnother line") == [
        "A line without a stop",
        "Another line",
    ]


def test_empty_text_has_no_pieces():
    assert split_sentences("") == []
```

`humanizer/tests/test_guards.py`:

```python
import pytest

from guards import accept_rewrite, should_skip


def few_tokens(_sentence):
    return 10


@pytest.mark.parametrize(
    "sentence",
    [
        "Call the `print` function to show output.",
        "This is a **very** important idea today.",
        "Here the *main* idea is quite simple.",
        "We know that x = 5 holds in this case.",
        "The cost is $5 for each of the items.",
        "Use \\frac to write the fraction out.",
        "Check whether a < b before you continue.",
        "Too short here.",
    ],
)
def test_sentences_that_must_keep_their_wording(sentence):
    assert should_skip(sentence, few_tokens) is True


def test_plain_sentence_is_rewritten():
    assert should_skip("A variable is a name for a value.", few_tokens) is False


def test_sentence_over_the_token_limit_is_skipped():
    sentence = "A variable is a name for a value."
    assert should_skip(sentence, lambda _s: 127, max_length=128) is True
    assert should_skip(sentence, lambda _s: 126, max_length=128) is False


def test_rewrite_is_accepted_when_it_keeps_length_and_numbers():
    assert accept_rewrite("There are 12 months in a year.", "A year contains 12 months in total.")


@pytest.mark.parametrize(
    "rewrite",
    [
        "",
        "   ",
        "Months exist.",
        "There are several months in a single year.",
        "There are 13 months in a single year.",
    ],
)
def test_bad_rewrites_are_rejected(rewrite):
    assert accept_rewrite("There are 12 months in a year.", rewrite) is False


def test_decimal_must_survive_whole():
    assert accept_rewrite("Pi is about 3.14 in value.", "The value of pi is about 3 or so.") is False
```

`humanizer/tests/test_humanize.py`:

```python
import pytest

from humanize import ModelUnavailable, humanize_text


def count_tokens(_sentence):
    return 10


def rewrite_all(sentence, **_params):
    return [f"Rewritten: {sentence}"]


def test_each_sentence_is_paraphrased_separately():
    seen = []

    def paraphrase(sentence, **_params):
        seen.append(sentence)
        return [f"Rewritten: {sentence}"]

    result = humanize_text("A first full sentence. A second full sentence.", paraphrase, count_tokens)

    assert seen == ["A first full sentence.", "A second full sentence."]
    assert result.text == "Rewritten: A first full sentence. Rewritten: A second full sentence."
    assert result.sentences_total == 2
    assert result.sentences_rewritten == 2


def test_whitespace_between_sentences_is_kept():
    result = humanize_text("A first full sentence.\n\nA second full sentence.", rewrite_all, count_tokens)
    assert result.text == "Rewritten: A first full sentence.\n\nRewritten: A second full sentence."


def test_guarded_sentence_keeps_its_text_and_never_reaches_the_model():
    def paraphrase(sentence, **_params):
        assert "`" not in sentence
        return [f"Rewritten: {sentence}"]

    result = humanize_text("Call `print` to show text. A plain full sentence.", paraphrase, count_tokens)

    assert result.text == "Call `print` to show text. Rewritten: A plain full sentence."
    assert result.sentences_total == 2
    assert result.sentences_rewritten == 1


def test_rejected_rewrite_keeps_the_original():
    result = humanize_text(
        "There are 12 months in a year.",
        lambda _s, **_p: ["There are 13 months in a year."],
        count_tokens,
    )
    assert result.text == "There are 12 months in a year."
    assert result.sentences_rewritten == 0


def test_one_failed_sentence_does_not_fail_the_text():
    def paraphrase(sentence, **_params):
        if sentence.startswith("Broken"):
            raise RuntimeError("generate failed")
        return [f"Rewritten: {sentence}"]

    result = humanize_text("Broken full sentence here. A plain full sentence.", paraphrase, count_tokens)

    assert result.text == "Broken full sentence here. Rewritten: A plain full sentence."
    assert result.sentences_rewritten == 1


def test_model_unavailable_propagates():
    def paraphrase(_sentence, **_params):
        raise ModelUnavailable("no model")

    with pytest.raises(ModelUnavailable):
        humanize_text("A plain full sentence.", paraphrase, count_tokens)


def test_params_reach_the_paraphraser():
    captured = {}

    def paraphrase(sentence, **params):
        captured.update(params)
        return [f"Rewritten: {sentence}"]

    humanize_text("A plain full sentence.", paraphrase, count_tokens, {"num_beams": 3})

    assert captured == {"num_beams": 3}
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `cd humanizer && .venv/Scripts/python.exe -m pytest tests -q`
Expected: collection errors with `ModuleNotFoundError` for `sentences`, `guards` and `humanize`.

- [ ] **Step 4: Implement the three modules**

`humanizer/sentences.py`:

```python
"""Split text into sentences without losing a single character of whitespace."""
import re
from typing import NamedTuple

import pysbd

_SEGMENTER = pysbd.Segmenter(language="en", clean=False)
_LINE_BREAKS = re.compile(r"(\n+)")


class Piece(NamedTuple):
    text: str
    is_sentence: bool


def _split_line(line: str) -> list[Piece]:
    pieces = []
    cursor = 0
    for segment in _SEGMENTER.segment(line):
        sentence = segment.strip()
        if not sentence:
            continue
        start = line.find(sentence, cursor)
        if start == -1:
            # pysbd altered the text, so treat the remainder as one sentence.
            break
        if start > cursor:
            pieces.append(Piece(line[cursor:start], False))
        pieces.append(Piece(sentence, True))
        cursor = start + len(sentence)

    remainder = line[cursor:]
    if remainder.strip():
        leading = len(remainder) - len(remainder.lstrip())
        trailing = len(remainder.rstrip())
        if leading:
            pieces.append(Piece(remainder[:leading], False))
        pieces.append(Piece(remainder[leading:trailing], True))
        if remainder[trailing:]:
            pieces.append(Piece(remainder[trailing:], False))
    elif remainder:
        pieces.append(Piece(remainder, False))
    return pieces


def split_sentences(text: str) -> list[Piece]:
    pieces = []
    for part in _LINE_BREAKS.split(text):
        if not part:
            continue
        if part.startswith("\n"):
            pieces.append(Piece(part, False))
        else:
            pieces.extend(_split_line(part))
    return pieces
```

`humanizer/guards.py`:

```python
"""Decide which sentences may be rewritten and which rewrites may be kept.

A kept sentence is always safe; a wrong rewrite is an error in teaching material.
"""
import re
from typing import Callable

_MARKUP = re.compile(r"[`*]")
_FORMULA = re.compile(r"[$\\=^<>{}]")
_NUMBER = re.compile(r"\d+(?:[.,]\d+)*")

MIN_WORDS = 4
MIN_WORD_RATIO = 0.5


def should_skip(sentence: str, count_tokens: Callable[[str], int], max_length: int = 128) -> bool:
    if _MARKUP.search(sentence) or _FORMULA.search(sentence):
        return True
    if len(sentence.split()) < MIN_WORDS:
        return True
    return count_tokens(sentence) > max_length - 2


def accept_rewrite(original: str, rewrite: str) -> bool:
    if not rewrite.strip():
        return False
    if len(rewrite.split()) < len(original.split()) * MIN_WORD_RATIO:
        return False
    return set(_NUMBER.findall(original)) <= set(_NUMBER.findall(rewrite))
```

`humanizer/humanize.py`:

```python
"""Paraphrase text one sentence at a time, keeping anything unsafe to rewrite."""
import logging
from typing import Callable, NamedTuple

from guards import accept_rewrite, should_skip
from sentences import split_sentences

logger = logging.getLogger(__name__)

DEFAULT_MAX_LENGTH = 128


class ModelUnavailable(Exception):
    """The model could not be loaded, so no sentence can be paraphrased."""


class HumanizeResult(NamedTuple):
    text: str
    sentences_total: int
    sentences_rewritten: int


def _rewrite(sentence, paraphrase_fn, params):
    try:
        outputs = paraphrase_fn(sentence, **params)
    except ModelUnavailable:
        raise
    except Exception:
        logger.exception("paraphrase failed; keeping the original sentence")
        return None
    rewrite = outputs[0].strip() if outputs else ""
    return rewrite if accept_rewrite(sentence, rewrite) else None


def humanize_text(
    text: str,
    paraphrase_fn: Callable[..., list[str]],
    count_tokens: Callable[[str], int],
    params: dict | None = None,
) -> HumanizeResult:
    params = params or {}
    max_length = params.get("max_length", DEFAULT_MAX_LENGTH)
    output = []
    total = rewritten = 0
    for piece in split_sentences(text):
        if not piece.is_sentence:
            output.append(piece.text)
            continue
        total += 1
        rewrite = None
        if not should_skip(piece.text, count_tokens, max_length):
            rewrite = _rewrite(piece.text, paraphrase_fn, params)
        if rewrite is None:
            output.append(piece.text)
        else:
            output.append(rewrite)
            rewritten += 1
    return HumanizeResult("".join(output), total, rewritten)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd humanizer && .venv/Scripts/python.exe -m pytest tests -q`
Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add humanizer/conftest.py humanizer/requirements-test.txt humanizer/sentences.py humanizer/guards.py humanizer/humanize.py humanizer/tests
git commit -m "feat(humanizer): sentence splitting, guards and humanize_text"
```

---

### Task 2: Paraphraser, HTTP API and container

**Files:**
- Create: `humanizer/paraphraser.py`
- Create: `humanizer/app.py`
- Create: `humanizer/requirements.txt`
- Create: `humanizer/Dockerfile`
- Create: `humanizer/README.md`
- Test: `humanizer/tests/test_app.py`

**Interfaces:**
- Consumes: `humanize.humanize_text`, `humanize.ModelUnavailable` (Task 1)
- Produces:
  - `paraphraser.paraphrase(question: str, num_beams=5, num_beam_groups=5, num_return_sequences=1, repetition_penalty=10.0, diversity_penalty=3.0, no_repeat_ngram_size=2, temperature=0.7, max_length=128) -> list[str]`
  - `paraphraser.count_tokens(sentence: str) -> int`
  - `paraphraser.status() -> dict` with keys `device`, `model_loaded`
  - `POST /humanize` with body `{"text": str, "params": {...}?}`, returning `{"text": str, "sentences_total": int, "sentences_rewritten": int}`
  - `GET /health`, returning `{"status": "ok", "device": str | None, "model_loaded": bool}`

- [ ] **Step 1: Write the failing test**

`humanizer/tests/test_app.py`:

```python
import pytest
from fastapi.testclient import TestClient

import app as app_module
import paraphraser
from humanize import ModelUnavailable


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(paraphraser, "paraphrase", lambda s, **_p: [f"Rewritten: {s}"])
    monkeypatch.setattr(paraphraser, "count_tokens", lambda _s: 10)
    return TestClient(app_module.app)


def test_humanize_returns_text_and_counts(client):
    response = client.post("/humanize", json={"text": "A first full sentence. Call `x` now please."})

    assert response.status_code == 200
    assert response.json() == {
        "text": "Rewritten: A first full sentence. Call `x` now please.",
        "sentences_total": 2,
        "sentences_rewritten": 1,
    }


def test_one_failed_sentence_still_returns_200(client, monkeypatch):
    def paraphrase(sentence, **_params):
        if sentence.startswith("Broken"):
            raise RuntimeError("generate failed")
        return [f"Rewritten: {sentence}"]

    monkeypatch.setattr(paraphraser, "paraphrase", paraphrase)

    response = client.post("/humanize", json={"text": "Broken full sentence here. A plain full sentence."})

    assert response.status_code == 200
    assert response.json()["text"] == "Broken full sentence here. Rewritten: A plain full sentence."


def test_params_are_forwarded(client, monkeypatch):
    captured = {}

    def paraphrase(sentence, **params):
        captured.update(params)
        return [f"Rewritten: {sentence}"]

    monkeypatch.setattr(paraphraser, "paraphrase", paraphrase)

    client.post("/humanize", json={"text": "A plain full sentence.", "params": {"num_beams": 3}})

    assert captured == {"num_beams": 3}


def test_unknown_param_is_rejected(client):
    response = client.post("/humanize", json={"text": "Some text.", "params": {"device": "cpu"}})
    assert response.status_code == 422


def test_oversized_text_is_rejected(client):
    response = client.post("/humanize", json={"text": "a" * 20001})
    assert response.status_code == 422


def test_model_load_failure_returns_503(client, monkeypatch):
    def count_tokens(_sentence):
        raise ModelUnavailable("no model")

    monkeypatch.setattr(paraphraser, "count_tokens", count_tokens)

    response = client.post("/humanize", json={"text": "A plain full sentence."})

    assert response.status_code == 503


def test_health_does_not_load_the_model(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "device": None, "model_loaded": False}
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd humanizer && .venv/Scripts/python.exe -m pytest tests/test_app.py -q`
Expected: collection error with `ModuleNotFoundError: No module named 'app'`.

- [ ] **Step 3: Implement the paraphraser and the API**

`humanizer/paraphraser.py`:

```python
"""The T5 paraphraser. The only module that imports torch or transformers."""
import os
import threading

from humanize import ModelUnavailable

MODEL_NAME = os.environ.get("HUMANIZER_MODEL", "humarin/chatgpt_paraphraser_on_T5_base")

_tokenizer = None
_model = None
_device = None
_load_lock = threading.Lock()
_generate_lock = threading.Lock()


def _load():
    global _tokenizer, _model, _device
    with _load_lock:
        if _model is not None:
            return
        try:
            import torch
            from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

            device = "cuda" if torch.cuda.is_available() else "cpu"
            _tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
            _model = AutoModelForSeq2SeqLM.from_pretrained(MODEL_NAME).to(device)
            _device = device
        except Exception as exc:
            raise ModelUnavailable(str(exc)) from exc


def status() -> dict:
    return {"device": _device, "model_loaded": _model is not None}


def count_tokens(sentence: str) -> int:
    _load()
    return len(_tokenizer(f"paraphrase: {sentence}").input_ids)


def paraphrase(
    question,
    num_beams=5,
    num_beam_groups=5,
    num_return_sequences=1,
    repetition_penalty=10.0,
    diversity_penalty=3.0,
    no_repeat_ngram_size=2,
    temperature=0.7,
    max_length=128,
):
    _load()
    input_ids = _tokenizer(
        f"paraphrase: {question}",
        return_tensors="pt",
        padding="longest",
        max_length=max_length,
        truncation=True,
    ).input_ids.to(_device)

    with _generate_lock:
        outputs = _model.generate(
            input_ids,
            temperature=temperature,
            repetition_penalty=repetition_penalty,
            num_return_sequences=num_return_sequences,
            no_repeat_ngram_size=no_repeat_ngram_size,
            num_beams=num_beams,
            num_beam_groups=num_beam_groups,
            max_length=max_length,
            diversity_penalty=diversity_penalty,
        )

    return _tokenizer.batch_decode(outputs, skip_special_tokens=True)
```

`humanizer/app.py`:

```python
"""HTTP API for the humanizer. Internal only: it has no authentication."""
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field

import paraphraser
from humanize import ModelUnavailable, humanize_text

MAX_TEXT_LENGTH = 20000

app = FastAPI(title="Humanizer")


class ParaphraseParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    num_beams: int | None = None
    num_beam_groups: int | None = None
    num_return_sequences: int | None = None
    repetition_penalty: float | None = None
    diversity_penalty: float | None = None
    no_repeat_ngram_size: int | None = None
    temperature: float | None = None
    max_length: int | None = None


class HumanizeRequest(BaseModel):
    text: str = Field(max_length=MAX_TEXT_LENGTH)
    params: ParaphraseParams | None = None


class HumanizeResponse(BaseModel):
    text: str
    sentences_total: int
    sentences_rewritten: int


@app.get("/health")
def health():
    return {"status": "ok", **paraphraser.status()}


@app.post("/humanize", response_model=HumanizeResponse)
def humanize(request: HumanizeRequest):
    params = request.params.model_dump(exclude_none=True) if request.params else {}
    try:
        return humanize_text(
            request.text,
            lambda sentence, **kwargs: paraphraser.paraphrase(sentence, **kwargs),
            lambda sentence: paraphraser.count_tokens(sentence),
            params,
        )._asdict()
    except ModelUnavailable as exc:
        raise HTTPException(status_code=503, detail=f"Model unavailable: {exc}") from exc
```

The lambdas look `paraphraser.paraphrase` up at call time, which is what lets the tests replace it.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd humanizer && .venv/Scripts/python.exe -m pytest tests -q`
Expected: all tests pass, without torch installed.

- [ ] **Step 5: Add runtime dependencies, Dockerfile and README**

`humanizer/requirements.txt` (the `transformers` pin is confirmed in Task 5):

```
fastapi>=0.115,<1
uvicorn>=0.30,<1
pysbd==0.3.4
torch>=2.4,<3
transformers==4.46.3
sentencepiece>=0.2,<1
protobuf>=4,<6
```

`humanizer/Dockerfile`:

```dockerfile
FROM python:3.12-slim

# CPU wheels by default. For a GPU host, build with the matching CUDA index, e.g.
# --build-arg TORCH_INDEX=https://download.pytorch.org/whl/cu126
ARG TORCH_INDEX=https://download.pytorch.org/whl/cpu

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 HF_HOME=/models

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir --extra-index-url "$TORCH_INDEX" -r requirements.txt
COPY *.py ./

RUN addgroup --system humanizer && adduser --system --group humanizer \
    && mkdir -p /models && chown humanizer:humanizer /models
USER humanizer

EXPOSE 8100
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8100"]
```

`humanizer/README.md`:

````markdown
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
````

- [ ] **Step 6: Commit**

```bash
git add humanizer/paraphraser.py humanizer/app.py humanizer/requirements.txt humanizer/Dockerfile humanizer/README.md humanizer/tests/test_app.py
git commit -m "feat(humanizer): paraphraser, HTTP API and container"
```

---

### Task 3: Draft walker in `coursegen`

**Files:**
- Create: `backend/coursegen/humanize.py`
- Modify: `backend/dailytaiyari/settings.py` (after line 434, `COURSEGEN_ASYNC = ...`)
- Test: `backend/coursegen/tests_humanize.py`

**Interfaces:**
- Consumes: `POST /humanize` response shape (Task 2); `coursegen.notehtml.render_blocks`, `coursegen.notehtml.estimate_reading_minutes`
- Produces: `coursegen.humanize.humanize_draft(kind: str, draft: dict, *, previous: dict | None = None, time_budget_s: float) -> dict`. It mutates and returns `draft`. Settings `HUMANIZER_URL`, `HUMANIZER_TIME_BUDGET_S`, `HUMANIZER_READ_TIMEOUT_S`.

- [ ] **Step 1: Write the failing tests**

`backend/coursegen/tests_humanize.py`:

```python
"""Tests for the humanizer hook. The service itself is stubbed at the HTTP layer."""
from unittest.mock import Mock, patch

import requests
from django.test import SimpleTestCase, override_settings

from coursegen.humanize import humanize_draft

URL = 'http://humanizer:8100'


def service_response(text):
    return Mock(
        status_code=200,
        raise_for_status=Mock(),
        json=Mock(return_value={
            'text': f'H: {text}', 'sentences_total': 1, 'sentences_rewritten': 1,
        }),
    )


def fake_post(_url, json, timeout):
    return service_response(json['text'])


def content_draft():
    return {'topics': [{
        'topic_name': 'Variables',
        'note': {
            'title': 'Variables',
            'blocks': [
                {'type': 'lead', 'text': 'Lead text.'},
                {'type': 'heading', 'text': 'A heading', 'level': 3},
                {'type': 'paragraph', 'text': 'Paragraph text.'},
                {'type': 'bullets', 'items': ['Bullet one.', 'Bullet two.']},
                {'type': 'numbers', 'items': ['Step one.']},
                {'type': 'code', 'text': 'x = 1', 'language': 'python'},
                {'type': 'callout', 'variant': 'tip', 'title': 'A title', 'text': 'Callout text.'},
                {'type': 'table', 'headers': ['Head'], 'rows': [['Cell']]},
                {'type': 'quote', 'text': 'Quote text.', 'attribution': 'Someone'},
                {'type': 'divider'},
            ],
            'html': '<p>old</p>',
            'estimated_time_minutes': 3,
            'include': True,
        },
        'quiz': {'questions': [{'question_text': 'Q?', 'explanation': 'Because.'}]},
        'assignments': [{'title': 'A', 'instructions': [{'type': 'paragraph', 'text': 'Do it.'}]}],
        'coding_problems': [{'title': 'C', 'statement': [{'type': 'paragraph', 'text': 'Solve.'}]}],
    }]}


def outline_draft():
    return {
        'course': {'name': 'Python', 'subtitle': 'Sub', 'description': 'Course text.',
                   'highlights': ['Highlight.']},
        'subjects': [{
            'name': 'Core', 'description': 'Subject text.',
            'chapters': [{
                'name': 'Basics', 'description': 'Chapter text.',
                'topics': [{'name': 'Loops', 'summary': 'Topic text.',
                            'objectives': ['Objective.']}],
            }],
        }],
    }


def meta_draft():
    return {'course': {
        'subtitle': 'Sub',
        'description': 'Plain description.',
        'description_blocks': [
            {'type': 'heading', 'text': 'A heading', 'level': 3},
            {'type': 'paragraph', 'text': 'Block text.'},
        ],
        'description_html': '<p>old</p>',
        'highlights': ['Highlight.'],
        'refund_policy': 'Refund text.',
    }}


@override_settings(HUMANIZER_URL=URL, HUMANIZER_READ_TIMEOUT_S=120)
class HumanizeDraftTests(SimpleTestCase):
    def run_draft(self, kind, draft, **kwargs):
        kwargs.setdefault('time_budget_s', 600)
        with patch('coursegen.humanize.requests.post', side_effect=fake_post) as post:
            result = humanize_draft(kind, draft, **kwargs)
        return result, post

    def test_content_changes_only_prose_blocks(self):
        result, post = self.run_draft('content', content_draft())
        topic = result['topics'][0]
        blocks = topic['note']['blocks']

        self.assertEqual(blocks[0]['text'], 'H: Lead text.')
        self.assertEqual(blocks[1]['text'], 'A heading')
        self.assertEqual(blocks[2]['text'], 'H: Paragraph text.')
        self.assertEqual(blocks[3]['items'], ['H: Bullet one.', 'H: Bullet two.'])
        self.assertEqual(blocks[4]['items'], ['H: Step one.'])
        self.assertEqual(blocks[5]['text'], 'x = 1')
        self.assertEqual(blocks[6]['text'], 'H: Callout text.')
        self.assertEqual(blocks[6]['title'], 'A title')
        self.assertEqual(blocks[7]['rows'], [['Cell']])
        self.assertEqual(blocks[8]['text'], 'H: Quote text.')
        self.assertEqual(blocks[8]['attribution'], 'Someone')

        self.assertEqual(topic['quiz']['questions'][0]['explanation'], 'Because.')
        self.assertEqual(topic['assignments'][0]['instructions'][0]['text'], 'Do it.')
        self.assertEqual(topic['coding_problems'][0]['statement'][0]['text'], 'Solve.')
        self.assertEqual(post.call_count, 7)

    def test_content_html_and_reading_time_are_rerendered(self):
        draft = content_draft()
        draft['topics'][0]['note']['blocks'][2]['text'] = ' '.join(['word'] * 1000) + '.'
        result, _post = self.run_draft('content', draft)
        note = result['topics'][0]['note']

        self.assertIn('H: Lead text.', note['html'])
        self.assertNotIn('<p>old</p>', note['html'])
        self.assertEqual(note['estimated_time_minutes'], 5)

    def test_outline_changes_descriptions_and_summaries_only(self):
        result, post = self.run_draft('outline', outline_draft())

        self.assertEqual(result['course']['description'], 'H: Course text.')
        self.assertEqual(result['course']['subtitle'], 'Sub')
        self.assertEqual(result['course']['highlights'], ['Highlight.'])
        subject = result['subjects'][0]
        self.assertEqual(subject['description'], 'H: Subject text.')
        chapter = subject['chapters'][0]
        self.assertEqual(chapter['description'], 'H: Chapter text.')
        self.assertEqual(chapter['name'], 'Basics')
        self.assertEqual(chapter['topics'][0]['summary'], 'H: Topic text.')
        self.assertEqual(chapter['topics'][0]['objectives'], ['Objective.'])
        self.assertEqual(post.call_count, 4)

    def test_meta_changes_description_and_rerenders_html(self):
        result, _post = self.run_draft('meta', meta_draft())
        course = result['course']

        self.assertEqual(course['description'], 'H: Plain description.')
        self.assertEqual(course['description_blocks'][0]['text'], 'A heading')
        self.assertEqual(course['description_blocks'][1]['text'], 'H: Block text.')
        self.assertIn('H: Block text.', course['description_html'])
        self.assertEqual(course['refund_policy'], 'Refund text.')
        self.assertEqual(course['highlights'], ['Highlight.'])

    def test_report_counts_sentences(self):
        result, _post = self.run_draft('outline', outline_draft())
        self.assertEqual(result['humanizer'], {
            'status': 'complete', 'sentences_total': 4,
            'sentences_rewritten': 4, 'fields_skipped': 0,
        })

    def test_rewrite_over_the_field_limit_keeps_the_original(self):
        draft = outline_draft()
        original = 'x' * 799
        draft['subjects'][0]['chapters'][0]['topics'][0]['summary'] = original
        result, _post = self.run_draft('outline', draft)

        topic = result['subjects'][0]['chapters'][0]['topics'][0]
        self.assertEqual(topic['summary'], original)
        self.assertEqual(result['humanizer']['status'], 'partial')
        self.assertEqual(result['humanizer']['fields_skipped'], 1)
        self.assertEqual(result['humanizer']['sentences_rewritten'], 3)

    def test_unchanged_text_from_the_previous_draft_is_not_sent(self):
        previous = outline_draft()
        draft = outline_draft()
        draft['subjects'][0]['description'] = 'A new subject text.'
        result, post = self.run_draft('outline', draft, previous=previous)

        self.assertEqual(post.call_count, 1)
        self.assertEqual(result['subjects'][0]['description'], 'H: A new subject text.')
        self.assertEqual(result['course']['description'], 'Course text.')
        self.assertEqual(result['humanizer']['status'], 'complete')

    def test_service_failure_keeps_text_and_stops_calling(self):
        for error in (requests.ConnectionError('down'), requests.Timeout('slow')):
            with self.subTest(error=error):
                with patch('coursegen.humanize.requests.post', side_effect=error) as post:
                    result = humanize_draft('outline', outline_draft(), time_budget_s=600)

                self.assertEqual(post.call_count, 1)
                self.assertEqual(result['course']['description'], 'Course text.')
                self.assertEqual(result['humanizer']['status'], 'failed')
                self.assertEqual(result['humanizer']['fields_skipped'], 4)

    def test_non_200_response_keeps_text(self):
        bad = Mock(raise_for_status=Mock(side_effect=requests.HTTPError('503')))
        with patch('coursegen.humanize.requests.post', return_value=bad) as post:
            result = humanize_draft('outline', outline_draft(), time_budget_s=600)

        self.assertEqual(post.call_count, 1)
        self.assertEqual(result['course']['description'], 'Course text.')
        self.assertEqual(result['humanizer']['status'], 'failed')

    def test_malformed_response_keeps_text(self):
        bad = Mock(raise_for_status=Mock(), json=Mock(return_value=['not', 'a', 'dict']))
        with patch('coursegen.humanize.requests.post', return_value=bad):
            result = humanize_draft('outline', outline_draft(), time_budget_s=600)

        self.assertEqual(result['course']['description'], 'Course text.')
        self.assertEqual(result['humanizer']['status'], 'failed')

    def test_failure_after_some_success_is_partial(self):
        responses = [service_response('Course text.'), requests.ConnectionError('down')]
        with patch('coursegen.humanize.requests.post', side_effect=responses):
            result = humanize_draft('outline', outline_draft(), time_budget_s=600)

        self.assertEqual(result['course']['description'], 'H: Course text.')
        self.assertEqual(result['subjects'][0]['description'], 'Subject text.')
        self.assertEqual(result['humanizer']['status'], 'partial')
        self.assertEqual(result['humanizer']['fields_skipped'], 3)

    def test_spent_budget_makes_no_calls(self):
        result, post = self.run_draft('outline', outline_draft(), time_budget_s=0)

        post.assert_not_called()
        self.assertEqual(result['course']['description'], 'Course text.')
        self.assertEqual(result['humanizer']['status'], 'partial')
        self.assertEqual(result['humanizer']['fields_skipped'], 4)

    def test_budget_running_out_mid_draft_stops_calls(self):
        clock = iter([0, 1])
        with patch('coursegen.humanize.time.monotonic', side_effect=lambda: next(clock, 700)), \
                patch('coursegen.humanize.requests.post', side_effect=fake_post) as post:
            result = humanize_draft('outline', outline_draft(), time_budget_s=600)

        self.assertEqual(post.call_count, 1)
        self.assertEqual(result['humanizer']['fields_skipped'], 3)


class HumanizeDisabledTests(SimpleTestCase):
    @override_settings(HUMANIZER_URL='')
    def test_empty_url_makes_no_call_and_changes_nothing(self):
        draft = outline_draft()
        with patch('coursegen.humanize.requests.post') as post:
            result = humanize_draft('outline', draft, time_budget_s=600)

        post.assert_not_called()
        self.assertEqual(result, outline_draft())

    @override_settings(HUMANIZER_URL=URL)
    def test_unknown_kind_changes_nothing(self):
        with patch('coursegen.humanize.requests.post') as post:
            result = humanize_draft('other', {'a': 1}, time_budget_s=600)

        post.assert_not_called()
        self.assertEqual(result, {'a': 1})
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && venv/Scripts/python.exe manage.py test coursegen.tests_humanize`
Expected: import error for `coursegen.humanize`.

- [ ] **Step 3: Add the settings and implement the walker**

In `backend/dailytaiyari/settings.py`, directly after the `COURSEGEN_ASYNC = ...` line:

```python
# Optional paraphrasing service for generated course prose. Empty means off.
HUMANIZER_URL = config('HUMANIZER_URL', default='')
HUMANIZER_TIME_BUDGET_S = config('HUMANIZER_TIME_BUDGET_S', default=600, cast=int)
HUMANIZER_READ_TIMEOUT_S = config('HUMANIZER_READ_TIMEOUT_S', default=120, cast=int)
```

`backend/coursegen/humanize.py`:

```python
"""Send a draft's prose through the optional humanizer service.

The service lives in the top-level ``humanizer/`` folder and owns the model. This
module only decides which draft fields are prose, posts them, and writes back what
returns. Any failure keeps the generated text, so a job never fails because of it.
"""
from __future__ import annotations

import logging
import time

import requests
from django.conf import settings

from .notehtml import estimate_reading_minutes, render_blocks

logger = logging.getLogger(__name__)

# These mirror the limits in schema.py, so a longer rewrite can't be clipped later.
NOTE_TEXT_LIMIT = 4000
LIST_ITEM_LIMIT = 500
TOPIC_SUMMARY_LIMIT = 800
SECTION_DESCRIPTION_LIMIT = 1500
OUTLINE_DESCRIPTION_LIMIT = 4000
META_DESCRIPTION_LIMIT = 6000

CONNECT_TIMEOUT_S = 5

_PROSE_BLOCKS = ('lead', 'paragraph', 'callout', 'quote')
_LIST_BLOCKS = ('bullets', 'numbers')


def _block_fields(blocks):
    for block in blocks or []:
        kind = block.get('type')
        if kind in _PROSE_BLOCKS:
            yield block, 'text', NOTE_TEXT_LIMIT
        elif kind in _LIST_BLOCKS:
            items = block.get('items') or []
            for index in range(len(items)):
                yield items, index, LIST_ITEM_LIMIT


def _outline_fields(draft):
    yield draft.get('course') or {}, 'description', OUTLINE_DESCRIPTION_LIMIT
    for subject in draft.get('subjects') or []:
        yield subject, 'description', SECTION_DESCRIPTION_LIMIT
        for chapter in subject.get('chapters') or []:
            yield chapter, 'description', SECTION_DESCRIPTION_LIMIT
            for topic in chapter.get('topics') or []:
                yield topic, 'summary', TOPIC_SUMMARY_LIMIT


def _content_fields(draft):
    for topic in draft.get('topics') or []:
        yield from _block_fields((topic.get('note') or {}).get('blocks'))


def _meta_fields(draft):
    course = draft.get('course') or {}
    yield course, 'description', META_DESCRIPTION_LIMIT
    yield from _block_fields(course.get('description_blocks'))


_FIELDS = {'outline': _outline_fields, 'content': _content_fields, 'meta': _meta_fields}


def _text_at(container, key):
    if isinstance(container, dict):
        return container.get(key)
    return container[key]


def _post(url, text):
    response = requests.post(
        f'{url.rstrip("/")}/humanize',
        json={'text': text},
        timeout=(CONNECT_TIMEOUT_S, settings.HUMANIZER_READ_TIMEOUT_S),
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict) or not isinstance(payload.get('text'), str):
        raise ValueError('unexpected humanizer response')
    return (
        payload['text'],
        int(payload.get('sentences_total') or 0),
        int(payload.get('sentences_rewritten') or 0),
    )


def _rerender(kind, draft):
    if kind == 'content':
        for topic in draft.get('topics') or []:
            note = topic.get('note') or {}
            if note.get('blocks'):
                note['html'] = render_blocks(note['blocks'])
                note['estimated_time_minutes'] = estimate_reading_minutes(note['blocks'])
    elif kind == 'meta':
        course = draft.get('course') or {}
        if course.get('description_blocks'):
            course['description_html'] = render_blocks(course['description_blocks'])


def humanize_draft(kind, draft, *, previous=None, time_budget_s):
    """Rewrite ``draft``'s prose in place and return it; see the module docstring."""
    url = settings.HUMANIZER_URL
    fields = _FIELDS.get(kind)
    if not url or fields is None:
        return draft

    already_done = set()
    if previous:
        already_done = {_text_at(c, k) for c, k, _limit in fields(previous)}

    deadline = time.monotonic() + time_budget_s
    total = rewritten = skipped = succeeded = 0
    unreachable = False

    for container, key, limit in fields(draft):
        text = _text_at(container, key)
        if not text or text in already_done:
            continue
        if unreachable or time.monotonic() >= deadline:
            skipped += 1
            continue
        try:
            rewrite, sentences_total, sentences_rewritten = _post(url, text)
        except (requests.RequestException, ValueError, TypeError) as exc:
            logger.warning('humanizer: keeping generated text (%s)', exc)
            unreachable = True
            skipped += 1
            continue

        succeeded += 1
        total += sentences_total
        if len(rewrite) > limit:
            skipped += 1
            continue
        container[key] = rewrite
        rewritten += sentences_rewritten

    if unreachable and not succeeded:
        status = 'failed'
    elif skipped:
        status = 'partial'
    else:
        status = 'complete'

    _rerender(kind, draft)
    draft['humanizer'] = {
        'status': status,
        'sentences_total': total,
        'sentences_rewritten': rewritten,
        'fields_skipped': skipped,
    }
    logger.info('humanizer: %s draft %s', kind, draft['humanizer'])
    return draft
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && venv/Scripts/python.exe manage.py test coursegen.tests_humanize`
Expected: `OK`.

- [ ] **Step 5: Commit**

```bash
git add backend/coursegen/humanize.py backend/coursegen/tests_humanize.py backend/dailytaiyari/settings.py
git commit -m "feat(coursegen): humanizer draft walker, off unless configured"
```

---

### Task 4: Wire it into the worker path and Compose

**Files:**
- Modify: `backend/coursegen/generation.py` (`_draft_for_prompt` at line 591, `run_job` at line 605, `apply_refinement` at line 641)
- Modify: `backend/coursegen/tasks.py:59-62`
- Modify: `backend/docker-compose.yml` (after line 60, top-level `volumes:`, and a new service before `nginx`)
- Test: `backend/coursegen/tests_humanize.py`

**Interfaces:**
- Consumes: `coursegen.humanize.humanize_draft` (Task 3)
- Produces: `generation.run_job(job, *, topics=None, humanize=False)` and `generation.apply_refinement(job, instruction, *, humanize=False)`

- [ ] **Step 1: Write the failing tests**

Append to `backend/coursegen/tests_humanize.py`. Add these imports at the top of the file, with the others:

```python
from coursegen.models import CourseGenerationJob
from coursegen.tests import OUTLINE_RESPONSE, _StudioTestCase
```

Append at the end:

```python
@override_settings(HUMANIZER_URL=URL, HUMANIZER_READ_TIMEOUT_S=120, HUMANIZER_TIME_BUDGET_S=600)
class HumanizePipelineTests(_StudioTestCase):
    def worker_job(self):
        return CourseGenerationJob.objects.create(
            tenant=self.tenant, created_by=self.admin, kind='outline', prompt='A course',
        )

    def test_worker_generate_humanizes_the_draft(self):
        from coursegen.tasks import run_generation_job

        job = self.worker_job()
        with self.stub_provider(), self.stub_llm(OUTLINE_RESPONSE), \
                patch('coursegen.humanize.requests.post', side_effect=fake_post):
            run_generation_job(str(job.id))

        job.refresh_from_db()
        self.assertEqual(job.status, 'preview')
        self.assertEqual(job.draft['course']['description'], 'H: Learn Python.')
        self.assertEqual(job.draft['humanizer']['status'], 'complete')

    def test_service_outage_still_leaves_a_reviewable_draft(self):
        from coursegen.tasks import run_generation_job

        job = self.worker_job()
        with self.stub_provider(), self.stub_llm(OUTLINE_RESPONSE), patch(
            'coursegen.humanize.requests.post', side_effect=requests.ConnectionError('down'),
        ):
            run_generation_job(str(job.id))

        job.refresh_from_db()
        self.assertEqual(job.status, 'preview')
        self.assertEqual(job.draft['course']['description'], 'Learn Python.')
        self.assertEqual(job.draft['humanizer']['status'], 'failed')

    def test_worker_refine_sends_only_changed_text(self):
        from coursegen.tasks import run_generation_job

        job = self.worker_job()
        with self.stub_provider(), self.stub_llm(OUTLINE_RESPONSE), \
                patch('coursegen.humanize.requests.post', side_effect=fake_post):
            run_generation_job(str(job.id))

        refined = OUTLINE_RESPONSE.replace('"Learn Python."', '"H: Learn Python."').replace(
            '"weightage": 100,', '"weightage": 100, "description": "A new subject text.",'
        )
        with self.stub_provider(), self.stub_llm(refined) as llm, \
                patch('coursegen.humanize.requests.post', side_effect=fake_post) as post:
            run_generation_job(str(job.id), 'refine', 'Add a subject description')

        job.refresh_from_db()
        # The report is bookkeeping, so it must not reach the model's prompt.
        self.assertNotIn('"humanizer"', llm.call_args.args[1][1]['content'])
        self.assertEqual(post.call_count, 1)
        self.assertEqual(job.draft['subjects'][0]['description'], 'H: A new subject text.')
        self.assertEqual(job.draft['course']['description'], 'H: Learn Python.')

    def test_inline_generation_does_not_humanize(self):
        with self.stub_provider(), self.stub_llm(OUTLINE_RESPONSE), \
                patch('coursegen.humanize.requests.post') as post:
            response = self.post(self.admin, '/jobs/', {
                'kind': 'outline', 'prompt': 'A beginner Python course',
            })

        self.assertEqual(response.status_code, 201)
        post.assert_not_called()
        job = CourseGenerationJob.objects.get(id=response.data['id'])
        self.assertEqual(job.draft['course']['description'], 'Learn Python.')
        self.assertNotIn('humanizer', job.draft)

    def test_budget_is_reduced_by_llm_time(self):
        from coursegen.generation import _humanized, _Meter

        job = self.worker_job()
        meter = _Meter()
        meter.elapsed_ms = 1_000_000
        with patch('coursegen.generation.humanize_draft', side_effect=lambda k, d, **kw: kw) as hook:
            _humanized(job, {}, meter)

        self.assertEqual(hook.call_args.kwargs['time_budget_s'], 400)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && venv/Scripts/python.exe manage.py test coursegen.tests_humanize.HumanizePipelineTests`
Expected: `test_inline_generation_does_not_humanize` passes. The other four fail or error, including an `ImportError` for `_humanized` in `test_budget_is_reduced_by_llm_time`.

- [ ] **Step 3: Wire the hook into `generation.py`**

Add to the imports at the top of `backend/coursegen/generation.py`, with the other relative imports. Also add `from django.conf import settings` if the module doesn't already import it:

```python
from .humanize import humanize_draft
```

Add this directly above `def run_job`:

```python
# Leaves room inside the task's 1500-second soft limit for everything else.
HUMANIZE_DEADLINE_S = 1400


def _humanized(job, draft, meter, *, previous=None):
    """Run the optional humanizer within whatever time the job has left."""
    budget = min(settings.HUMANIZER_TIME_BUDGET_S, HUMANIZE_DEADLINE_S - meter.elapsed_ms / 1000)
    return humanize_draft(job.kind, draft, previous=previous, time_budget_s=budget)
```

In `run_job`, change the signature and add the step before `_store_result`:

```python
def run_job(job, *, topics=None, humanize=False):
```

```python
    if humanize:
        draft = _humanized(job, draft, meter)
    _store_result(job, draft, meter, resolved)
```

In `apply_refinement`, make the same two changes. `job.draft` still holds the previous draft at this point:

```python
def apply_refinement(job, instruction, *, humanize=False):
```

```python
    if humanize:
        draft = _humanized(job, draft, meter, previous=job.draft)
    _store_result(job, draft, meter, resolved, accumulate=True)
```

In `_draft_for_prompt`, drop the report alongside `stats`:

```python
    draft.pop('stats', None)
    draft.pop('humanizer', None)
```

In `backend/coursegen/tasks.py`, change the two calls:

```python
        if mode == 'refine':
            generation.apply_refinement(job, instruction or '', humanize=True)
        else:
            generation.run_job(job, topics=topics or [], humanize=True)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && venv/Scripts/python.exe manage.py test coursegen`
Expected: `OK`, with the 58 existing tests plus the new ones.

- [ ] **Step 5: Add the Compose service**

In `backend/docker-compose.yml`, add this to the `&app-env` list directly after the `CODE_JUDGE_PARALLELISM` line:

```yaml
      # Optional paraphrasing of generated course prose. Empty keeps it off; see
      # ../humanizer/README.md.
      - HUMANIZER_URL=${HUMANIZER_URL:-}
      - HUMANIZER_TIME_BUDGET_S=${HUMANIZER_TIME_BUDGET_S:-600}
      - HUMANIZER_READ_TIMEOUT_S=${HUMANIZER_READ_TIMEOUT_S:-120}
```

Add this service directly above the `nginx:` service:

```yaml
  # Paraphrases generated course prose, used by the aigen worker over HTTP. Only
  # starts with `--profile humanizer`, because the model image and download are large.
  # SECURITY: never publish ports (internal docker network only); the API has no auth.
  humanizer:
    build: ../humanizer
    profiles: ["humanizer"]
    restart: unless-stopped
    volumes:
      - humanizer_models:/models
```

Add `humanizer_models:` to the top-level `volumes:` list.

Run: `cd backend && DB_NAME=x DB_USER=x DB_PASSWORD=x DB_HOST=x SECRET_KEY=x DEBUG=x ALLOWED_HOSTS=x OPENAI_API_KEY=x docker compose config --services`
Expected: the output doesn't list `humanizer`. If Docker isn't installed, parse the file instead with `venv/Scripts/python.exe -c "import yaml; d = yaml.safe_load(open('docker-compose.yml')); print(d['services']['humanizer'], 'ports' in d['services']['humanizer'])"`, and confirm it prints `False` for ports.

- [ ] **Step 6: Commit**

```bash
git add backend/coursegen/generation.py backend/coursegen/tasks.py backend/coursegen/tests_humanize.py backend/docker-compose.yml
git commit -m "feat(coursegen): humanize drafts on the worker, add compose profile"
```

---

### Task 5: Real model run

**Files:**
- Modify: `humanizer/requirements.txt` (confirm the `transformers` pin)
- Modify: `humanizer/README.md` (add measured results)

**Interfaces:**
- Consumes: `paraphraser.paraphrase`, `humanize.humanize_text` (Tasks 1 and 2)

- [ ] **Step 1: Install the real dependencies in a separate environment**

This downloads roughly 2–3 GB of PyTorch wheels. Install torch from the CUDA index first, because PyPI's Windows wheels are CPU-only and a higher PyPI version would otherwise win.

```bash
cd humanizer && python -m venv .venv-model && .venv-model/Scripts/python.exe -m pip install -q torch==2.5.1 --index-url https://download.pytorch.org/whl/cu121 && .venv-model/Scripts/python.exe -m pip install -q -r requirements.txt
```

Expected: exits 0, and `.venv-model/Scripts/python.exe -c "import torch; print(torch.cuda.is_available())"` prints `True`. Confirm that `.venv-model` shows as ignored with `git check-ignore humanizer/.venv-model`. If it doesn't, add `humanizer/.venv-model/` to `.gitignore` in this task's commit.

- [ ] **Step 2: Run the model on sample prose**

Write this to the session scratchpad as `humanizer_smoke.py`, and run it from `humanizer/` with `.venv-model/Scripts/python.exe <scratchpad>/humanizer_smoke.py`. The script adds the current directory to the path.

```python
import os
import sys
import time

sys.path.insert(0, os.getcwd())

import paraphraser
from humanize import humanize_text

SAMPLES = [
    "A variable is a named location in memory that stores a value. "
    "You can change that value while the program runs. "
    "Python decides the type of a variable automatically when you assign to it.",
    "A loop repeats a block of code until a condition is met. "
    "Use the `for` loop when you know the number of iterations. "
    "A year has 12 months, and most programs treat them as numbers from 1 to 12.",
    "Recursion does not always make a program faster. "
    "Each call uses extra memory on the stack, so very deep recursion can crash the program.",
]

started = time.perf_counter()
total = rewritten = 0
for sample in SAMPLES:
    result = humanize_text(sample, paraphraser.paraphrase, paraphraser.count_tokens)
    total += result.sentences_total
    rewritten += result.sentences_rewritten
    print("BEFORE:", sample)
    print("AFTER: ", result.text)
    print()
elapsed = time.perf_counter() - started
print(paraphraser.status())
print(f"{rewritten}/{total} sentences rewritten, {elapsed / max(total, 1):.2f}s per sentence")
```

The first run downloads the model from Hugging Face (`humarin/chatgpt_paraphraser_on_T5_base`).

Expected: every sample prints a rewrite with no exceptions in the log, and `status()` shows `device` as `cuda`. Run it a second time so that the timing excludes the download and the model load.

If `generate()` raises an error about `num_beam_groups` or `diversity_penalty`, or the load fails on this version, try the next older `transformers` release until it works. Update the pin in `requirements.txt` to the version that works.

- [ ] **Step 3: Check the rewrites by reading them**

Compare each BEFORE and AFTER for meaning. Record any changed meaning, in particular whether "does not always" kept its negation, for the final report. The guards don't catch this kind of change, so report it as found. Don't weaken or tune the guards in this step.

- [ ] **Step 4: Measure CPU speed**

Run the same script with `CUDA_VISIBLE_DEVICES=""` set, to get seconds per sentence on CPU.

- [ ] **Step 5: Record the results**

Append to `humanizer/README.md`, using the measured values from Steps 2 and 4:

```markdown
## Measured speed

Default parameters, 5-beam search, on sample course prose:

| Hardware | Seconds per sentence |
|---|---|
| RTX 3050 Laptop (4 GB) | <measured GPU value> |
| CPU | <measured CPU value> |
```

- [ ] **Step 6: Run all the tests again**

Run: `cd humanizer && .venv/Scripts/python.exe -m pytest tests -q`
Run: `cd backend && venv/Scripts/python.exe manage.py test coursegen`
Expected: both pass.

- [ ] **Step 7: Commit**

```bash
git add humanizer/requirements.txt humanizer/README.md
git commit -m "docs(humanizer): confirm transformers pin and record measured speed"
```
