"""Stub translation service — runs in CI and local dev when NLLB is off.

Returns the original text prefixed with ``[stub EN→en] ``. Lets the
end-to-end cache/UI flow exercise a real HTTP round-trip without
needing to download a 2.4GB model.

This file is intentionally minimal so it loads in a slim Python
container — see infra/docker-compose.yaml `translation` service.
"""

from __future__ import annotations

from fastapi import FastAPI

from services.translation.contract import TranslateRequest, TranslateResponse

app = FastAPI(title="DIP Translation — STUB", version="0.0.1")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "mode": "stub"}


@app.post("/translate", response_model=TranslateResponse)
def translate(req: TranslateRequest) -> TranslateResponse:
    # Echo the input with a clearly-stub marker so tests can assert against it
    # and so a human eyeballing the UI can immediately tell the real model is off.
    prefix = f"[stub {req.source_language}→{req.target_language}] "
    return TranslateResponse(
        translated_text=prefix + req.text,
        source_language=req.source_language
        if req.source_language != "auto"
        else "en",
        target_language=req.target_language,
        model_name="stub",
        model_version="0.0.1",
        confidence=None,
        character_count=len(req.text),
    )
