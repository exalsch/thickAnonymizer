from thickanon.detectors.llm import iter_chunks

def test_short_text_single_chunk():
    assert iter_chunks("hello", max_chars=100) == [(0, "hello")]

def test_long_text_split_with_overlap_and_bases():
    text = "abcdefghij"  # 10 chars
    chunks = iter_chunks(text, max_chars=4, overlap=1)
    # each chunk must be reconstructable from its base
    for base, chunk in chunks:
        assert text[base:base + len(chunk)] == chunk
    # full coverage: every index appears in at least one chunk
    covered = set()
    for base, chunk in chunks:
        covered.update(range(base, base + len(chunk)))
    assert covered == set(range(len(text)))
    assert all(len(c) <= 4 for _, c in chunks)

def test_empty_text():
    assert iter_chunks("", max_chars=4) == []


def test_small_max_chars_does_not_explode_chunk_count():
    text = "x" * 1000
    chunks = iter_chunks(text, max_chars=100, overlap=200)  # overlap > max_chars
    # clamped overlap (<=50) -> step >= 50 -> far fewer than 100s of chunks
    assert len(chunks) < 30
    # still covers everything
    covered = set()
    for base, c in chunks:
        covered.update(range(base, base + len(c)))
    assert covered == set(range(1000))
