from pathlib import Path


def read_fragments(path) -> list[str]:
    return [Path(path).read_text(encoding="utf-8")]


def write_fragments(path, fragments: list[str]) -> None:
    Path(path).write_text(fragments[0], encoding="utf-8")
