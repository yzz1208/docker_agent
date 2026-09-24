from typing import Any

from docker_agent.rag.embeddings import BgeM3Embedder


class FakeModel:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def encode(self, texts: list[str], **kwargs: Any) -> list[list[float]]:
        self.calls.append({"texts": texts, **kwargs})
        return [[1.0, 0.0] for _ in texts]


def test_embedder_requests_normalized_embeddings() -> None:
    model = FakeModel()
    embedder = BgeM3Embedder(model_name="fake", model=model, batch_size=4)

    vectors = embedder.embed_documents(["docker daemon", "container logs"])

    assert vectors == [[1.0, 0.0], [1.0, 0.0]]
    assert model.calls[0]["normalize_embeddings"] is True
    assert model.calls[0]["batch_size"] == 4


def test_embed_query_returns_one_vector() -> None:
    embedder = BgeM3Embedder(model_name="fake", model=FakeModel())

    assert embedder.embed_query("docker volume") == [1.0, 0.0]


def test_embedder_exposes_warmup_state_for_injected_model() -> None:
    embedder = BgeM3Embedder(model_name="fake", model=FakeModel())

    assert embedder.is_loaded is True
    embedder.warmup()
    assert embedder.is_loaded is True
