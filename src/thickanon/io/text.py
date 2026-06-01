from pathlib import Path


def read_fragments(path) -> list[str]:
    return [Path(path).read_text(encoding="utf-8")]


def write_fragments(path, fragments: list[str]) -> None:
    if len(fragments) != 1:
        raise ValueError(
            f"Fragment count mismatch: expected 1 fragment, got {len(fragments)}"
        )
    Path(path).write_text(fragments[0], encoding="utf-8")
