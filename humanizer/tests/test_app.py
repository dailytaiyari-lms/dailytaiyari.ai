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
