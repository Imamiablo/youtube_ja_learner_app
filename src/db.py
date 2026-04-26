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
        try:
            yield conn
        finally:
            conn.close()

    def initialize(self) -> None:
        """ Create database tables if they don't exist and apply some small migrations """

        with self.connection() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS articles (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    source_value TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    notes_json TEXT DEFAULT '{}'
                );
                    
                    CREATE TABLE IF NOT EXISTS segments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    article_id INTEGER NOT NULL,
                    segment_index INTEGER NOT NULL,
                    start_sec REAL NOT NULL DEFAULT 0,
                    duration_sec REAL NOT NULL DEFAULT 0,
                    japanese_text TEXt NOT NULL,
                    translation_text TEXT DEFAULT '',
                    furigana_html TEXT DEFAULT '',
                    FOREIGN KEY (article_id) REFERENCES articles (id) ON DELETE CASCADE
                );
                
                CREATE TABLE IF NOT EXISTS vocab_Items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    article_id INTEGER NOT NULL,
                    source_segment_id INTEGER,
                    surface_form TEXT NOT NULL,
                    display_form TEXT INTEGER,
                    base_form TEXT NOT NULL,
                    orth_base TEXT DEFAULT '',
                    reading_hiragana TEXT DEFAULT '',
                    pos TEXT DEFAULT '',
                    pos_detail_1 TEXT DEFAULT '',
                    pos_detail_2 TEXT DEFAULT '',
                    word_type TEXT DEFAULT '',
                    translation TEXT DEFAULT '',
                    jlpt_level_estimate TEXT DEFAULT '',
                    topic_score REAL NOT NULL DEFAULT 0,
                    occurence_count INTEGER NOT NULL DEFAULT 1,
                    UNIQUE (article_id , base_form)
                    FOREIGN KEY (article_id) REFERENCES articles (id) ON DELETE CASCADE,
                    FOREIGN KEY (source_segment_id) REFERENCES segments (id) ON DELETE SET NULL
                );
                    
                CREATE TABLE IF NOT EXISTS vocab_progress (
                    vocab_item_id INTEGER PRIMARY KEY,
                    rating TEXT NOT NULL DEFAULT '',
                    ignored INTEGER NOT NULL DEFAULT 0,
                    review_count INTEGER NOT NULL DEFAULT 0,
                    last_reviewed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (vocab_item_id) REFERENCES vocab_Items (id) ON DELETE CASCADE
                );
                """
            )
            self._ensure_column(conn, "vocab_items", "display_form", "TEXT DEFAULT ''")
            self._ensure_column(conn, "vocab_items", "orth_base", "TEXT DEFAULT ''")
            self._ensure_column(conn, "vocab_items", "pos_detail_1", "TEXT DEFAULT ''")
            self._ensure_column(conn, "vocab_items", "pos_detail_2", "TEXT DEFAULT ''")
            self._ensure_column(conn, "vocab_items", "word_type", "TEXT DEFAULT ''")
            self._ensure_column(conn, "vocab_items", "topic_score", "REAL NOT NULL DEFAULT 0")
            self._ensure_column(conn, "vocab_progress", "ignored", "INTEGER NOT NULL DEFAULT 0")

    @staticmethod
    def _ensure_column (conn: sqlite3.Connection, table_name: str, column_name: str, ddl: str) -> None:
        existing = {
            row["name"]
            for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()
        }
        if column_name not in existing:
            conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {ddl}")

    def create_article(
            self,
            *,
            title: str,
            source_type: str,
            source_value: str,
            notes: dict[str, Any] | None = None,
    ) -> int:
        """Insert a new article and return its database ID."""
        with self.connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO articles (title, source_type, source_value, notes_json)
                VALUES (?, ?, ?, ?)
                """,
                (title, source_type, source_value, json.dumps(notes or {}, ensure_ascii=False)),
            )
            return int(cursor.lastrowid)

    def insert_segments(self, article_id: int, segments: list[dict[str, Any]]) -> list[int]:
        """Insert article segments and return their database IDs in order."""
        ids: list[int] = []
        with self.connection() as conn:
            for segment in segments:
                cursor = conn.execute(
                    """
                    INSERT INTO segments (article_id,
                                          segment_index,
                                          start_sec,
                                          duration_sec,
                                          japanese_text,
                                          translation_text,
                                          furigana_html)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        article_id,
                        segment["segment_index"],
                        segment.get("start_sec", 0),
                        segment.get("duration_sec", 0),
                        segment["japanese_text"],
                        segment.get("translation_text", ""),
                        segment.get("furigana_html", ""),
                    ),
                )
                ids.append(int(cursor.lastrowid))
        return ids

    def insert_vocab_items(self, article_id: int, vocab_items: list[dict[str, Any]]) -> None:
        """Insert or update vocabulary rows for an article."""
        with self.connection() as conn:
            for item in vocab_items:
                conn.execute(
                    """
                    INSERT INTO vocab_items (article_id,
                                             source_segment_id,
                                             surface_form,
                                             display_form,
                                             base_form,
                                             orth_base,
                                             reading_hiragana,
                                             pos,
                                             pos_detail_1,
                                             pos_detail_2,
                                             word_type,
                                             translation_text,
                                             jlpt_level_estimate,
                                             topic_score,
                                             occurrence_count)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(article_id, base_form)
                        DO
                    UPDATE SET
                        occurrence_count = occurrence_count + excluded.occurrence_count,
                        display_form = CASE
                        WHEN excluded.display_form != '' THEN excluded.display_form
                        ELSE vocab_items.display_form
                    END
                    ,
                            orth_base = CASE
                                WHEN excluded.orth_base != '' THEN excluded.orth_base
                                ELSE vocab_items.orth_base
                    END
                    ,
                            word_type = CASE
                                WHEN excluded.word_type != '' THEN excluded.word_type
                                ELSE vocab_items.word_type
                    END
                    ,
                            topic_score = MAX(vocab_items.topic_score, excluded.topic_score),
                            translation_text = CASE
                                WHEN excluded.translation_text != '' THEN excluded.translation_text
                                ELSE vocab_items.translation_text
                    END
                    ,
                            jlpt_level_estimate = CASE
                                WHEN excluded.jlpt_level_estimate != '' THEN excluded.jlpt_level_estimate
                                ELSE vocab_items.jlpt_level_estimate
                    END
                    """,
                    (
                        article_id,
                        item.get("source_segment_id"),
                        item["surface_form"],
                        item.get("display_form", ""),
                        item["base_form"],
                        item.get("orth_base", ""),
                        item.get("reading_hiragana", ""),
                        item.get("pos", ""),
                        item.get("pos_detail_1", ""),
                        item.get("pos_detail_2", ""),
                        item.get("word_type", ""),
                        item.get("translation_text", ""),
                        item.get("jlpt_level_estimate", ""),
                        float(item.get("topic_score", 0)),
                        int(item.get("occurrence_count", 1)),
                    ),
                )

    def list_articles(self) -> list[dict[str, Any]]:
        """Return all saved articles, newest first."""
        with self.connection() as conn:
            rows = conn.execute(
                """
                SELECT id, title, source_type, source_value, created_at
                FROM articles
                ORDER BY id DESC
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def get_article(self, article_id: int) -> dict[str, Any] | None:
        """Return one article, including its segments and vocabulary."""
        with self.connection() as conn:
            article = conn.execute(
                "SELECT * FROM articles WHERE id = ?",
                (article_id,),
            ).fetchone()
            if article is None:
                return None

            segments = conn.execute(
                """
                SELECT *
                FROM segments
                WHERE article_id = ?
                ORDER BY segment_index ASC
                """,
                (article_id,),
            ).fetchall()

            vocab = conn.execute(
                """
                SELECT v.*,
                       COALESCE(p.rating, '')           AS rating,
                       COALESCE(p.review_count, 0)      AS review_count,
                       COALESCE(p.last_reviewed_at, '') AS last_reviewed_at,
                       COALESCE(p.ignored, 0)           AS ignored_in_reviews
                FROM vocab_items v
                         LEFT JOIN vocab_progress p ON p.vocab_item_id = v.id
                WHERE v.article_id = ?
                ORDER BY v.topic_score DESC, v.occurrence_count DESC, v.display_form ASC, v.base_form ASC
                """,
                (article_id,),
            ).fetchall()

        payload = dict(article)
        payload["notes"] = json.loads(payload.get("notes_json") or "{}")
        payload["segments"] = [dict(row) for row in segments]
        payload["vocab"] = [dict(row) for row in vocab]
        return payload

    def set_vocab_rating(self, vocab_item_id: int, rating: str) -> None:
        """Insert or update a user's latest rating for a vocabulary item."""
        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO vocab_progress (vocab_item_id, rating, ignored, review_count)
                VALUES (?, ?, 0, 1) ON CONFLICT(vocab_item_id)
                    DO
                UPDATE SET
                    rating = excluded.rating,
                    review_count = vocab_progress.review_count + 1,
                    last_reviewed_at = CURRENT_TIMESTAMP
                """,
                (vocab_item_id, rating),
            )

    def delete_article(self, article_id: int) -> None:
        """Delete an article and all dependent rows."""
        with self.connection() as conn:
            conn.execute("DELETE FROM articles WHERE id = ?", (article_id,))
