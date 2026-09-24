from collections.abc import Sequence
from typing import Any

from docker_agent.config import get_settings


class BgeM3Embedder:
    """Lazy SentenceTransformers wrapper for BAAI/bge-m3 dense embeddings.

    Importing ``sentence_transformers`` also imports PyTorch. Keeping that import
    inside ``model`` means lightweight commands and unit tests that inject a fake
    model do not require the native PyTorch DLLs to load during module import.
    """

    def __init__(
        self,
        *,
        model_name: str | None = None,
        device: str | None = None,
        cache_folder: str | None = None,
        batch_size: int | None = None,
        model: Any | None = None,
    ) -> None:
        settings = get_settings()
        self.model_name = model_name or settings.embedding_model
        self.device = device if device is not None else settings.embedding_device
        self.cache_folder = (
            cache_folder if cache_folder is not None else settings.embedding_cache_dir
        )
        self.batch_size = batch_size or settings.embedding_batch_size
        self._model = model

    @property
    def is_loaded(self) -> bool:
        """Whether the heavyweight embedding model is already resident."""

        return self._model is not None

    def warmup(self) -> None:
        """Load the embedding model without running a user query."""

        _ = self.model

    @property
    def model(self) -> Any:
        if self._model is None:
            # SentenceTransformers imports torch, which loads native DLLs on
            # Windows. Delay that work until an embedding is actually requested.
            from sentence_transformers import SentenceTransformer

            kwargs: dict[str, Any] = {}
            if self.device:
                kwargs["device"] = self.device
            if self.cache_folder:
                kwargs["cache_folder"] = self.cache_folder
            self._model = SentenceTransformer(self.model_name, **kwargs)
        return self._model

    def embed_documents(
        self,
        texts: Sequence[str],
        *,
        show_progress_bar: bool = True,
    ) -> list[list[float]]:
        """Embed document texts with normalized dense vectors."""

        if not texts:
            return []

        vectors = self.model.encode(
            list(texts),
            batch_size=self.batch_size,
            normalize_embeddings=True,
            show_progress_bar=show_progress_bar,
            convert_to_numpy=True,
        )
        return [[float(value) for value in vector] for vector in vectors]

    def embed_query(self, text: str) -> list[float]:
        """Embed one user query into the same normalized vector space."""

        vectors = self.embed_documents([text], show_progress_bar=False)
        if not vectors:
            raise ValueError("Query text must not be empty")
        return vectors[0]
