from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Protocol

from docker_agent.config import get_settings
from docker_agent.rag.store import HybridSearchResult
from docker_agent.rag.text import build_embedding_text


class PairScorer(Protocol):
    def score(self, query: str, passages: Sequence[str]) -> list[float]: ...


class BgeReranker:
    """Lazy Hugging Face wrapper for BAAI/bge-reranker-v2-m3.

    The model consumes query/passage pairs and returns one relevance logit per
    pair. We apply sigmoid so scores are easier to inspect while preserving the
    ranking induced by the raw logits.
    """

    def __init__(
        self,
        *,
        model_name: str | None = None,
        device: str | None = None,
        cache_dir: str | None = None,
        batch_size: int | None = None,
        max_length: int | None = None,
        use_fp16: bool | None = None,
        tokenizer: Any | None = None,
        model: Any | None = None,
    ) -> None:
        settings = get_settings()
        self.model_name = model_name or settings.rerank_model
        self.device = device if device is not None else (
            settings.rerank_device or settings.embedding_device
        )
        self.cache_dir = cache_dir if cache_dir is not None else (
            settings.rerank_cache_dir or settings.embedding_cache_dir
        )
        self.batch_size = batch_size or settings.rerank_batch_size
        self.max_length = max_length or settings.rerank_max_length
        self.use_fp16 = settings.rerank_use_fp16 if use_fp16 is None else use_fp16
        self._tokenizer = tokenizer
        self._model = model
        self._resolved_device: str | None = None

    def _ensure_loaded(self) -> None:
        if self._tokenizer is not None and self._model is not None:
            return

        import torch
        from transformers import AutoModelForSequenceClassification, AutoTokenizer

        device = self.device or ("cuda" if torch.cuda.is_available() else "cpu")
        common_kwargs: dict[str, Any] = {}
        if self.cache_dir:
            common_kwargs["cache_dir"] = self.cache_dir

        self._tokenizer = AutoTokenizer.from_pretrained(self.model_name, **common_kwargs)
        self._model = AutoModelForSequenceClassification.from_pretrained(
            self.model_name,
            **common_kwargs,
        )
        self._model.to(device)
        if self.use_fp16 and device.startswith("cuda"):
            self._model.half()
        self._model.eval()
        self._resolved_device = device

    def score(self, query: str, passages: Sequence[str]) -> list[float]:
        if not query.strip():
            raise ValueError("query must not be empty")
        if not passages:
            return []
        if self.batch_size <= 0:
            raise ValueError("rerank batch size must be positive")
        if self.max_length <= 0:
            raise ValueError("rerank max length must be positive")

        self._ensure_loaded()
        assert self._tokenizer is not None
        assert self._model is not None

        import torch

        device = self._resolved_device or self.device or "cpu"
        scores: list[float] = []
        for start in range(0, len(passages), self.batch_size):
            batch = list(passages[start : start + self.batch_size])
            pairs = [[query, passage] for passage in batch]
            inputs = self._tokenizer(
                pairs,
                padding=True,
                truncation=True,
                return_tensors="pt",
                max_length=self.max_length,
            )
            inputs = {key: value.to(device) for key, value in inputs.items()}
            with torch.no_grad():
                logits = self._model(**inputs, return_dict=True).logits.view(-1).float()
                normalized = torch.sigmoid(logits)
            scores.extend(float(value) for value in normalized.cpu().tolist())
        return scores


def build_rerank_passage(candidate: HybridSearchResult) -> str:
    return build_embedding_text(
        title=candidate.title,
        section_path=candidate.section_path,
        content=candidate.content,
    )


def rerank_candidates(
    query: str,
    candidates: Sequence[HybridSearchResult],
    scorer: PairScorer,
    *,
    top_k: int = 5,
) -> list[HybridSearchResult]:
    """Rerank an already-recalled candidate pool with a cross encoder."""

    if top_k <= 0:
        raise ValueError("top_k must be positive")
    if not candidates:
        return []

    passages = [build_rerank_passage(candidate) for candidate in candidates]
    scores = scorer.score(query, passages)
    if len(scores) != len(candidates):
        raise ValueError("reranker returned a score count that does not match candidates")

    reranked = list(candidates)
    for candidate, score in zip(reranked, scores, strict=True):
        candidate.rerank_score = float(score)

    reranked.sort(
        key=lambda item: (
            -(item.rerank_score if item.rerank_score is not None else float("-inf")),
            -item.rrf_score,
            item.chunk_id,
        )
    )
    return reranked[:top_k]
