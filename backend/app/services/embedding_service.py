"""
Embedding service with:
- Singleton SentenceTransformer (lazy-loaded once)
- SHA256-keyed bounded cache (avoids re-encoding identical texts)
- Async wrappers via run_in_executor (never blocks the event loop)
"""
import asyncio
import hashlib
import time
from collections import deque

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Bounded LRU cache
# 512 slots x ~384-dim floats x 4 bytes ≈ 800 KB — negligible.
# deque(maxlen=) gives O(1) append + automatic oldest-entry eviction,
# replacing the previous list.pop(0) which was O(n).
# ---------------------------------------------------------------------------
_CACHE_MAX = 512
_embedding_cache: dict[str, list[float]] = {}
# deque with maxlen evicts the leftmost (oldest) key automatically on append
_cache_order: deque[str] = deque(maxlen=_CACHE_MAX)


def _cache_get(key: str) -> list[float] | None:
    return _embedding_cache.get(key)


def _cache_set(key: str, value: list[float]) -> None:
    if key in _embedding_cache:
        return
    if len(_cache_order) >= _CACHE_MAX:
        # deque maxlen auto-evicts on append, but we must also remove from dict
        oldest = _cache_order[0]  # peek before deque drops it
        _embedding_cache.pop(oldest, None)
    _embedding_cache[key] = value
    _cache_order.append(key)  # deque auto-drops oldest when full


def _text_hash(text: str) -> str:
    """Stable cache key: SHA256 of first 2000 chars."""
    return hashlib.sha256(text[:2000].encode("utf-8", errors="ignore")).hexdigest()


def _deterministic_embedding(text: str, dim: int = 384) -> list[float]:
    """
    L2-normalized pseudo-vector when SentenceTransformer.encode fails (OOM, corrupt model, etc.).
    Same text always maps to the same vector — cosine similarity remains defined for demos.
    """
    raw = hashlib.sha256((text or "").encode("utf-8", errors="ignore")).digest()
    vec: list[float] = []
    for i in range(dim):
        b = raw[i % len(raw)]
        vec.append((b / 127.5) - 1.0)
    norm = sum(x * x for x in vec) ** 0.5 or 1.0
    return [x / norm for x in vec]


# ---------------------------------------------------------------------------
# Singleton model
# ---------------------------------------------------------------------------
class _EmbeddingModelSingleton:
    _instance = None
    _model_name: str | None = None

    @classmethod
    def get_model(cls):
        if cls._instance is None:
            settings = get_settings()
            from sentence_transformers import SentenceTransformer
            cls._instance = SentenceTransformer(settings.embedding_model)
            cls._model_name = settings.embedding_model
            logger.info("Loaded embedding model: %s", cls._model_name)
        return cls._instance

    @classmethod
    def get_embedding(cls, text: str) -> list[float]:
        key = _text_hash(text)
        cached = _cache_get(key)
        if cached is not None:
            return cached
        try:
            emb: list[float] = cls.get_model().encode(
                text, convert_to_numpy=True, normalize_embeddings=True
            ).tolist()
        except Exception as exc:
            logger.warning("get_embedding model.encode failed, using deterministic fallback: %s", exc)
            return _deterministic_embedding(text)
        _cache_set(key, emb)
        return emb

    @classmethod
    def get_embeddings(cls, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        results: list[list[float] | None] = [None] * len(texts)
        uncached_texts: list[str] = []
        uncached_indices: list[int] = []

        for i, text in enumerate(texts):
            key = _text_hash(text)
            cached = _cache_get(key)
            if cached is not None:
                results[i] = cached
            else:
                uncached_texts.append(text)
                uncached_indices.append(i)

        if uncached_texts:
            t0 = time.perf_counter()
            try:
                new_embs: list[list[float]] = cls.get_model().encode(
                    uncached_texts, convert_to_numpy=True, normalize_embeddings=True
                ).tolist()
            except Exception as exc:
                logger.warning(
                    "batch encode failed n=%d, using deterministic fallbacks: %s",
                    len(uncached_texts),
                    exc,
                )
                new_embs = []
            if len(new_embs) == len(uncached_texts):
                logger.info(
                    "embedding_latency_ms=%.1f n_texts=%d cache_hits=%d",
                    (time.perf_counter() - t0) * 1000,
                    len(uncached_texts),
                    len(texts) - len(uncached_texts),
                )
                for idx, text, emb in zip(uncached_indices, uncached_texts, new_embs):
                    _cache_set(_text_hash(text), emb)
                    results[idx] = emb
            else:
                for idx, text in zip(uncached_indices, uncached_texts):
                    results[idx] = _deterministic_embedding(text)
                    logger.debug("deterministic_embedding fallback for batch index=%s", idx)

        out: list[list[float]] = []
        for i, r in enumerate(results):
            if r is not None:
                out.append(r)
            else:
                t = texts[i] if i < len(texts) else ""
                out.append(_deterministic_embedding(t or "__empty__"))
        return out


# ---------------------------------------------------------------------------
# Synchronous API (used by KeyBERT and other blocking callers)
# ---------------------------------------------------------------------------
def get_embeddings(texts: list[str]) -> list[list[float]]:
    """Synchronous batch embedding with cache."""
    return _EmbeddingModelSingleton.get_embeddings(texts)


# ---------------------------------------------------------------------------
# Async API — two-layer cache + run_in_executor to avoid blocking the loop
#
# L1: in-process LRU (_embedding_cache, 512 slots)
# L2: Redis  (key = "emb:{sha256}", TTL = 24 h, stored as JSON bytes)
#
# Cache lookup order on a miss:
#   check L1 → check Redis L2 → model.encode() → write to both caches
# ---------------------------------------------------------------------------
_REDIS_EMB_TTL = 86400  # 24 hours


async def get_embeddings_async(texts: list[str]) -> list[list[float]]:
    """
    Async batch embedding with L1 (in-process LRU) and L2 (Redis) caches.
    Falls back to direct inference when Redis is unavailable.
    Use this in all async request handlers — never blocks the event loop.
    """
    import json as _json
    from app.cache.redis_client import cache_get, cache_set

    if not texts:
        return []

    results: list[list[float] | None] = [None] * len(texts)
    l1_miss_indices: list[int] = []

    # --- L1 check (in-process LRU) ---
    for i, text in enumerate(texts):
        val = _cache_get(_text_hash(text))
        if val is not None:
            results[i] = val
        else:
            l1_miss_indices.append(i)

    if not l1_miss_indices:
        return [r for r in results if r is not None]  # all filled from L1

    # --- L2 check (Redis) ---
    redis_miss_indices: list[int] = []
    for i in l1_miss_indices:
        raw = await cache_get(f"emb:{_text_hash(texts[i])}")
        if raw is not None:
            try:
                emb: list[float] = _json.loads(raw)
                results[i] = emb
                _cache_set(_text_hash(texts[i]), emb)  # backfill L1
            except (ValueError, TypeError):
                redis_miss_indices.append(i)
        else:
            redis_miss_indices.append(i)

    if not redis_miss_indices:
        return [r for r in results if r is not None]

    # --- Model inference for full misses ---
    # asyncio.get_running_loop() replaces the deprecated get_event_loop()
    # (deprecated in Python 3.10, raises DeprecationWarning in 3.11)
    inference_texts = [texts[i] for i in redis_miss_indices]
    loop = asyncio.get_running_loop()
    try:
        new_embs = await loop.run_in_executor(None, get_embeddings, inference_texts)
    except Exception as exc:
        logger.warning("get_embeddings_async executor failed: %s", exc)
        new_embs = []

    if len(new_embs) == len(redis_miss_indices):
        for i, emb in zip(redis_miss_indices, new_embs):
            results[i] = emb
            try:
                await cache_set(
                    f"emb:{_text_hash(texts[i])}",
                    _json.dumps(emb).encode(),
                    ttl_seconds=_REDIS_EMB_TTL,
                )
            except Exception:
                pass
    else:
        for i in redis_miss_indices:
            results[i] = _deterministic_embedding(texts[i] or "__empty__")

    return [
        r if r is not None else _deterministic_embedding(texts[j] or "__empty__")
        for j, r in enumerate(results)
    ]


async def get_embedding_async(text: str) -> list[float]:
    """Async single-text embedding — goes through the same two-layer cache."""
    results = await get_embeddings_async([text])
    if not results:
        return _deterministic_embedding(text or "__empty__")
    return results[0]
