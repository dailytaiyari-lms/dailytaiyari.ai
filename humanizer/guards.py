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
