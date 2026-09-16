from docker_agent.docs.audit import audit_chunks


def test_audit_chunks_reports_distribution_and_quality_flags() -> None:
    rows = [
        {
            "chunk_id": "c1",
            "document_id": "d1",
            "content": "one two three four five",
            "source_url": "https://docs.docker.com/example/",
            "section_path": ["Example"],
        },
        {
            "chunk_id": "c2",
            "document_id": "d1",
            "content": "```bash\ndocker info\n```",
            "source_url": "https://docs.docker.com/example/",
            "section_path": ["Example", "Command"],
        },
        {
            "chunk_id": "c3",
            "document_id": "d2",
            "content": "```bash\ndocker ps",
            "source_url": "",
            "section_path": [],
        },
        {
            "chunk_id": "c4",
            "document_id": "d2",
            "content": "{{< tip >}} stale shortcode",
            "source_url": "https://docs.docker.com/example/",
            "section_path": ["Example"],
        },
        {
            "chunk_id": "c5",
            "document_id": "d3",
            "content": "one two three four five",
            "source_url": "https://docs.docker.com/example/",
            "section_path": ["Duplicate"],
        },
    ]

    report = audit_chunks(rows, min_words=4, max_words=10)

    assert report.total_chunks == 5
    assert report.unique_documents == 3
    assert report.missing_source_url == 1
    assert report.missing_section_path == 1
    assert report.unbalanced_code_fences == 1
    assert report.shortcode_remnants == 1
    assert report.duplicate_contents == 1
    assert report.min_words > 0
    assert report.max_words <= 10


def test_audit_understands_longer_outer_code_fences() -> None:
    rows = [
        {
            "chunk_id": "nested-fence",
            "document_id": "d1",
            "content": "````markdown\n```bash\ndocker info\n```\n````",
            "source_url": "https://docs.docker.com/example/",
            "section_path": ["Example"],
        }
    ]

    report = audit_chunks(rows)

    assert report.unbalanced_code_fences == 0


def test_audit_empty_dataset() -> None:
    report = audit_chunks([])

    assert report.total_chunks == 0
    assert report.unique_documents == 0
    assert report.average_words == 0.0
