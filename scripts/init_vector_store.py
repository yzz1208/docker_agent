from docker_agent.rag.store import init_vector_store


def main() -> None:
    init_vector_store()
    print("Vector store is ready: pgvector extension + document_chunks table")


if __name__ == "__main__":
    main()
