import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator


class Database:
    """Small wrapper around sqlite3 with schema initialization."""

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        """Yield a configured SQLite connection."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")

    def initialize(self) -> None:
        """ Create database tables if they don't exist and apply some small migrations """

        with self.connection() as conn:
            conn.executescript(
                """
                
                """
            )

