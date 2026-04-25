"""NLLB-200 translation service.

Wraps the Hugging Face ``facebook/nllb-200-distilled-600M`` model behind
the same :class:`~services.translation.contract.TranslateRequest` /
:class:`TranslateResponse` as the stub. Swapping between the two is a
compose-profile toggle — no app-level code change.

Runs on CPU by default. To run on GPU, set ``NLLB_DEVICE=cuda:0`` in the
container env.

This module imports transformers lazily so the import cost is only paid
when the service actually boots (model load ≈ 10-30s on CPU).
"""

from __future__ import annotations

import logging
import os
from functools import lru_cache
from threading import Lock
from typing import Any

from fastapi import FastAPI, HTTPException

from services.translation.contract import TranslateRequest, TranslateResponse

logger = logging.getLogger("dip.translation.nllb")

# NLLB language codes differ from ISO 639-1 — a small mapping covers our
# v1 languages. Extend as we add source languages.
NLLB_CODE: dict[str, str] = {
    "en": "eng_Latn",
    "it": "ita_Latn",
    "de": "deu_Latn",
    "fr": "fra_Latn",
    "es": "spa_Latn",
    "nl": "nld_Latn",
    "ar": "arb_Arab",
}

MODEL_NAME = os.getenv("NLLB_MODEL", "facebook/nllb-200-distilled-600M")
MODEL_VERSION = MODEL_NAME.split("/")[-1]
DEVICE = os.getenv("NLLB_DEVICE", "cpu")
MAX_LENGTH = int(os.getenv("NLLB_MAX_LENGTH", "512"))

_load_lock = Lock()


@lru_cache(maxsize=1)
def _load() -> tuple[Any, Any]:
    """Lazy-load the model + tokenizer exactly once per process."""
    with _load_lock:
        logger.info("nllb.loading model=%s device=%s", MODEL_NAME, DEVICE)
        from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

        tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
        model = AutoModelForSeq2SeqLM.from_pretrained(MODEL_NAME)
        if DEVICE != "cpu":
            model = model.to(DEVICE)
        logger.info("nllb.loaded")
        return tokenizer, model


def _to_nllb(code: str) -> str:
    """Map ISO 639-1 to NLLB's 'xxx_Script' code."""
    base = code.split("-", 1)[0].lower()
    if base not in NLLB_CODE:
        raise ValueError(f"unsupported language for NLLB: {code}")
    return NLLB_CODE[base]


app = FastAPI(title="DIP Translation — NLLB-200", version=MODEL_VERSION)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "mode": "nllb", "model": MODEL_NAME, "device": DEVICE}


@app.on_event("startup")
def warmup() -> None:
    """Eagerly load the model at startup so the first request isn't cold."""
    _load()


@app.post("/translate", response_model=TranslateResponse)
def translate(req: TranslateRequest) -> TranslateResponse:
    try:
        src = _to_nllb(req.source_language) if req.source_language != "auto" else "eng_Latn"
        tgt = _to_nllb(req.target_language)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    tokenizer, model = _load()
    tokenizer.src_lang = src
    inputs = tokenizer(req.text, return_tensors="pt", truncation=True, max_length=MAX_LENGTH)
    if DEVICE != "cpu":
        inputs = {k: v.to(DEVICE) for k, v in inputs.items()}

    generated = model.generate(
        **inputs,
        forced_bos_token_id=tokenizer.convert_tokens_to_ids(tgt),
        max_length=MAX_LENGTH,
        num_beams=4,
    )
    translated = tokenizer.batch_decode(generated, skip_special_tokens=True)[0]

    return TranslateResponse(
        translated_text=translated,
        source_language=req.source_language,
        target_language=req.target_language,
        model_name=MODEL_NAME,
        model_version=MODEL_VERSION,
        confidence=None,  # NLLB doesn't expose a per-sentence confidence natively
        character_count=len(req.text),
    )
