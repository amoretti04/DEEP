"""Translation service.

Two layers:

* :mod:`services.translation.client` — HTTP client used by the API
  layer. Knows nothing about models; talks to whatever TRANSLATION_BACKEND
  points at. Swapping from ``stub`` to ``nllb_http`` is a config change.

* :mod:`services.translation.app` — the service itself. A FastAPI
  container that exposes ``POST /translate`` and either echoes
  (``stub`` mode) or runs NLLB-200 (``nllb`` mode).

Caching lives in the API layer (a separate concern), not here.
"""
