"""Open an explicitly existing SQLite database without creating a file."""

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


@contextmanager
def open_existing_sqlite(
    source: sqlite3.Connection | str | os.PathLike[str],
    *,
    mode: str,
    error_type: type[Exception],
) -> Iterator[sqlite3.Connection]:
    """Yield a caller connection or an existing path opened with SQLite URI mode."""
    if isinstance(source, sqlite3.Connection):
        yield source
        return

    if mode not in {"ro", "rw"}:
        raise ValueError("SQLite connection mode must be ro or rw")

    path = Path(source).expanduser()
    try:
        if not path.exists():
            raise error_type("SQLite database file does not exist")
        if not path.is_file():
            raise error_type("SQLite database path is not a regular file")
        database_uri = f"{path.resolve(strict=True).as_uri()}?mode={mode}"
    except error_type:
        raise
    except (OSError, ValueError) as exc:
        raise error_type("SQLite database path could not be validated") from exc

    try:
        conn = sqlite3.connect(database_uri, uri=True)
    except sqlite3.Error as exc:
        raise error_type("existing SQLite database could not be opened") from exc
    try:
        yield conn
    finally:
        conn.close()
