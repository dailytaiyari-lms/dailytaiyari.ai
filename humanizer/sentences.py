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
