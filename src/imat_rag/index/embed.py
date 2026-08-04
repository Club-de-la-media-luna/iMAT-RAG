"""Turn chunks into vectors, locally.

Embeddings are computed on this machine and never through an API. That is what
makes `rag search` work offline and keeps the system provider-agnostic — an
embedding API in the query path would reintroduce the network dependency
ADR-0002 exists to avoid.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any, Protocol

from pydantic import BaseModel

MODEL_NAME = "BAAI/bge-m3"
DIMENSIONS = 1024
MAX_SEQUENCE = 8192
"""BGE-M3's context. Chunks are far smaller, so nothing is truncated."""


class EmbedConfig(BaseModel, frozen=True):
    """Settings that change the vectors, and therefore the index."""

    model: str = MODEL_NAME
    dimensions: int = DIMENSIONS
    batch_size: int = 8
    """Small on purpose: 4 GB of VRAM, and the model itself takes ~2.2 GB."""

    normalize: bool = True
    """Cosine similarity via dot product on unit vectors."""

    device: str = "auto"


class Encoder(Protocol):  # pylint: disable=too-few-public-methods
    """The slice of sentence-transformers this package depends on.

    A one-method protocol on purpose: it is the seam that lets the index be
    tested without downloading a 2.2 GB model.
    """

    def encode(self, sentences: Any, **kwargs: Any) -> Any:
        """Encode one or more strings into vectors."""


def resolve_device(requested: str) -> str:
    """Pick a device, preferring the GPU when one is usable."""
    if requested != "auto":
        return requested
    try:
        # Lazy: importing torch costs seconds, and querying never needs it
        # unless a GPU is actually available.
        import torch  # pylint: disable=import-outside-toplevel
    except ImportError:  # pragma: no cover - torch is an extra
        return "cpu"
    return "cuda" if torch.cuda.is_available() else "cpu"


def load_encoder(config: EmbedConfig | None = None) -> Encoder:
    """Load BGE-M3.

    Imported inside the function so that importing this package never pays for
    torch — `rag paths` and `rag books` must stay instant.
    """
    # pylint: disable=import-outside-toplevel
    from sentence_transformers import SentenceTransformer

    config = config or EmbedConfig()
    model: Encoder = SentenceTransformer(
        config.model, device=resolve_device(config.device)
    )
    return model


def encode_texts(
    encoder: Encoder, texts: Sequence[str], config: EmbedConfig | None = None
) -> list[list[float]]:
    """Embed a batch of texts, returning plain lists for storage."""
    config = config or EmbedConfig()
    if not texts:
        return []
    vectors = encoder.encode(
        list(texts),
        batch_size=config.batch_size,
        normalize_embeddings=config.normalize,
        show_progress_bar=False,
        convert_to_numpy=True,
    )
    return [[float(value) for value in row] for row in vectors]


def batched(items: Sequence[Any], size: int) -> Iterable[Sequence[Any]]:
    """Split a sequence into runs of at most `size`."""
    for start in range(0, len(items), max(size, 1)):
        yield items[start : start + size]
