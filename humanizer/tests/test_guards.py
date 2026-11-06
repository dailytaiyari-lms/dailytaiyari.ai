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
