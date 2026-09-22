from pathlib import Path

from docker_agent.docs.pipeline import build_dataset

SELECTED_ROOT = Path("data/selected/docker-docs")
OUTPUT_DIR = Path("data/processed")


def main() -> None:
    documents, chunks = build_dataset(SELECTED_ROOT, OUTPUT_DIR)

    print(f"Built {len(documents)} documents")
    print(f"Built {len(chunks)} chunks")
    print(f"Documents: {OUTPUT_DIR / 'documents.jsonl'}")
    print(f"Chunks:    {OUTPUT_DIR / 'chunks.jsonl'}")


if __name__ == "__main__":
    main()
