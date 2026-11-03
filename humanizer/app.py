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
        # The lambdas look paraphraser's functions up at call time, so tests can replace them.
        return humanize_text(
            request.text,
            lambda sentence, **kwargs: paraphraser.paraphrase(sentence, **kwargs),
            lambda sentence: paraphraser.count_tokens(sentence),
            params,
        )._asdict()
    except ModelUnavailable as exc:
        raise HTTPException(status_code=503, detail=f"Model unavailable: {exc}") from exc
