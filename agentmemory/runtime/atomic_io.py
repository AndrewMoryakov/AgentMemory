from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


def atomic_write_text(path: Path, content: str, *, encoding: str = "utf-8") -> None:
    """Write text to `path` atomically.

    Pattern: write to a temp file in the same directory, fsync, then
    os.replace onto the target. A crash mid-write leaves the previous
    contents intact rather than a half-written file.

    Concurrent writers still need external locking — atomicity here means
    the on-disk file is never observed half-written, not that concurrent
    read-modify-write cycles serialize.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding=encoding,
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temp_file:
            temp_path = temp_file.name
            temp_file.write(content)
            temp_file.flush()
            os.fsync(temp_file.fileno())
        os.replace(temp_path, path)
        temp_path = None
    finally:
        if temp_path is not None:
            Path(temp_path).unlink(missing_ok=True)


def atomic_write_json(
    path: Path,
    data: Any,
    *,
    ensure_ascii: bool = True,
    indent: int | None = 2,
    encoding: str = "utf-8",
) -> None:
    """Serialize `data` to JSON and write atomically to `path`.

    Trailing newline matches the existing project convention.
    """
    body = json.dumps(data, ensure_ascii=ensure_ascii, indent=indent) + "\n"
    atomic_write_text(path, body, encoding=encoding)
