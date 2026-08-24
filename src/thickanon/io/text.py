
def read_fragments(path) -> list[str]:
    # newline="" keeps the file's own line endings inside the string. Without
    # it Python rewrites them on the way in and again on the way out, so on
    # Windows a LF file came back as CRLF: every line changed, in a tool whose
    # whole promise is that it only rewrites the spans it detected.
    with open(path, "r", encoding="utf-8", newline="") as handle:
        return [handle.read()]


def write_fragments(path, fragments: list[str]) -> None:
    if len(fragments) != 1:
        raise ValueError(
            f"Fragment count mismatch: expected 1 fragment, got {len(fragments)}"
        )
    with open(path, "w", encoding="utf-8", newline="") as handle:
        handle.write(fragments[0])
