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
