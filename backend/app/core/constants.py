"""Shared constants that used to be re-declared per module (Phase 3.5).

Keep this file small and dependency-free: it is imported by models, services
and API modules alike, so it must never import from ``app.services``.
"""

from __future__ import annotations

#: Reciprocal-rank-fusion smoothing constant for hybrid (dense + sparse)
#: retrieval. Knowledge retrieval reads its tunable copy from
#: ``settings.knowledge_retrieval_rrf_k``; user/project memory use this default.
RRF_K = 60

#: OpenRouter's API root. Admins often save ``https://openrouter.ai`` (the
#: website) as a connection ``base_url``; every OpenRouter client normalises
#: through :func:`normalize_openrouter_base_url` so requests hit the API and
#: not an HTML page.
OPENROUTER_API_BASE = "https://openrouter.ai/api/v1"
OPENROUTER_HOST = "openrouter.ai"


def normalize_openrouter_base_url(base_url: str | None) -> str:
    """Return an OpenRouter API root for a stored connection ``base_url``.

    * empty / ``None``            -> ``OPENROUTER_API_BASE``
    * ``https://openrouter.ai``   -> ``OPENROUTER_API_BASE`` (no ``/api/`` path)
    * anything else               -> unchanged minus trailing slashes, so a
      self-hosted or proxied endpoint keeps working.
    """
    base = (base_url or "").strip().rstrip("/")
    if not base:
        return OPENROUTER_API_BASE
    low = base.lower()
    if OPENROUTER_HOST in low and "/api/" not in low:
        return OPENROUTER_API_BASE
    return base
