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
