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
