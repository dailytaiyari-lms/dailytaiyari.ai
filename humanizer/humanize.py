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
