"""SQLite persistence: documents, pages, blocks, searchable chunks and task history.

Persistent document knowledge lives here. Short-lived agent state does not;
only a finished task's result summary is recorded, for history.
"""

from __future__ import annotations

import json
import re
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

from .chunking import Chunk
from .errors import StoreClosed
from .schemas import AgentResult, Block, DocStatus, DocumentContent, DocumentInfo, PageContent, Source, TextLine
from .textnorm import search_form

SCHEMA_VERSION = 2  # 2: the full-text index holds search_form(text), not the raw text

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS documents (
    id TEXT PRIMARY KEY, path TEXT UNIQUE NOT NULL, name TEXT NOT NULL, sha256 TEXT NOT NULL,
    size INTEGER, mtime REAL, pages INTEGER DEFAULT 0, total_pages INTEGER DEFAULT 0,
    status TEXT NOT NULL, doc_type TEXT DEFAULT 'unknown', engine TEXT DEFAULT '',
    error TEXT, mean_conf REAL, added_at TEXT
);
CREATE INDEX IF NOT EXISTS documents_sha ON documents(sha256);
CREATE TABLE IF NOT EXISTS pages (
    doc_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE, number INTEGER NOT NULL,
    width REAL, height REAL, source TEXT, markdown TEXT, lines TEXT, mean_conf REAL,
    rotation INTEGER, note TEXT, ocr_ms REAL, PRIMARY KEY (doc_id, number)
);
CREATE TABLE IF NOT EXISTS blocks (
    doc_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE, page INTEGER NOT NULL,
    idx INTEGER NOT NULL, label TEXT, text TEXT, bbox TEXT, conf REAL, PRIMARY KEY (doc_id, page, idx)
);
CREATE TABLE IF NOT EXISTS chunks (
    id INTEGER PRIMARY KEY, doc_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    page INTEGER, block_start INTEGER, block_end INTEGER, text TEXT, bbox TEXT, conf REAL,
    flagged INTEGER DEFAULT 0, search_text TEXT
);
CREATE INDEX IF NOT EXISTS chunks_doc ON chunks(doc_id);
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
    search_text, content='chunks', content_rowid='id', tokenize='porter unicode61'
);
CREATE TABLE IF NOT EXISTS embeddings (
    chunk_id INTEGER PRIMARY KEY REFERENCES chunks(id) ON DELETE CASCADE,
    model TEXT NOT NULL, dim INTEGER NOT NULL, vec BLOB NOT NULL
);
CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY, request TEXT, intent TEXT, state TEXT, created_at TEXT,
    duration_ms REAL, result TEXT
);
"""

_FTS_TRIGGERS = """
CREATE TRIGGER IF NOT EXISTS chunks_ai AFTER INSERT ON chunks BEGIN
    INSERT INTO chunks_fts(rowid, search_text) VALUES (new.id, new.search_text);
END;
CREATE TRIGGER IF NOT EXISTS chunks_ad AFTER DELETE ON chunks BEGIN
    INSERT INTO chunks_fts(chunks_fts, rowid, search_text) VALUES ('delete', old.id, old.search_text);
END;
"""

_WORD = re.compile(r"[\w$€£%.-]+", re.UNICODE)


def fts_query(text: str) -> str:
    """Turn free text into a safe FTS5 OR-query of quoted terms."""
    terms = [t.strip(".-") for t in _WORD.findall(search_form(text).lower())]
    terms = [t for t in terms if len(t) > 1 or t.isdigit()]
    return " OR ".join(f'"{t.replace(chr(34), "")}"' for t in dict.fromkeys(terms))


def _j(value: Any) -> str | None:
    return None if value is None else json.dumps(value)


def _bbox(raw: str | None) -> tuple[float, float, float, float] | None:
    return tuple(json.loads(raw)) if raw else None  # type: ignore[return-value]


class Store:
    """Thread-safe repository over one SQLite file."""

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._lock = threading.RLock()
        self._db = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA foreign_keys = ON")
        self._db.execute("PRAGMA journal_mode = WAL")
        self._db.executescript(_SCHEMA)
        self._migrate_search_index()
        self._db.executescript(_FTS_TRIGGERS)
        self._db.execute("INSERT OR IGNORE INTO meta VALUES ('schema_version', ?)", (str(SCHEMA_VERSION),))

        self._closed = False

    def _migrate_search_index(self) -> None:
        """Version 1 indexed the raw chunk text: add search_text, fill it, and rebuild the index from it.

        Runs under the write lock and re-checks inside it, so two processes opening the same old library at
        once migrate it once."""
        db = self._db
        if self._search_index_current():
            return
        db.execute("BEGIN IMMEDIATE")
        try:
            if self._search_index_current():  # another process finished first
                db.execute("COMMIT")
                return
            if "search_text" not in {row[1] for row in db.execute("PRAGMA table_info(chunks)")}:
                db.execute("ALTER TABLE chunks ADD COLUMN search_text TEXT")
            db.execute("DROP TRIGGER IF EXISTS chunks_ai")
            db.execute("DROP TRIGGER IF EXISTS chunks_ad")
            db.execute("DROP TABLE IF EXISTS chunks_fts")
            rows = db.execute("SELECT id, text FROM chunks").fetchall()
            db.executemany(
                "UPDATE chunks SET search_text = ? WHERE id = ?", [(search_form(t or ""), i) for i, t in rows]
            )
            db.execute(
                "CREATE VIRTUAL TABLE chunks_fts USING fts5(search_text, content='chunks', content_rowid='id', "
                "tokenize='porter unicode61')"
            )
            db.execute("INSERT INTO chunks_fts(chunks_fts) VALUES ('rebuild')")
            db.execute("UPDATE meta SET value = ? WHERE key = 'schema_version'", (str(SCHEMA_VERSION),))
            db.execute("COMMIT")
        except BaseException:
            db.execute("ROLLBACK")
            raise

    def _search_index_current(self) -> bool:
        row = self._db.execute("SELECT sql FROM sqlite_master WHERE name = 'chunks_fts'").fetchone()
        return row is not None and "search_text" in row[0]

    @property
    def closed(self) -> bool:
        return self._closed

    def close(self) -> None:
        """Close the connection. Idempotent; later use raises StoreClosed instead of a sqlite error."""
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._db.close()

    def __enter__(self) -> Store:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _conn(self) -> sqlite3.Connection:
        if self._closed:
            raise StoreClosed(f"The library database {self.path.name} is closed")
        return self._db

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            db = self._conn()
            db.execute("BEGIN")
            try:
                yield db
            except BaseException:
                db.execute("ROLLBACK")
                raise
            db.execute("COMMIT")

    def _all(self, sql: str, args: tuple[Any, ...] = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn().execute(sql, args).fetchall()

    # -- documents ---------------------------------------------------------

    @staticmethod
    def _doc(row: sqlite3.Row) -> DocumentInfo:
        data = dict(row)
        data["added_at"] = datetime.fromisoformat(data["added_at"]) if data["added_at"] else None
        return DocumentInfo(**data)

    def upsert_document(self, info: DocumentInfo) -> None:
        added = (info.added_at or datetime.now(UTC)).isoformat()
        with self.tx() as db:
            db.execute(
                """INSERT INTO documents VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET path=excluded.path, name=excluded.name, sha256=excluded.sha256,
                size=excluded.size, mtime=excluded.mtime, pages=excluded.pages, total_pages=excluded.total_pages,
                status=excluded.status, doc_type=excluded.doc_type, engine=excluded.engine, error=excluded.error,
                mean_conf=excluded.mean_conf""",
                (
                    info.id,
                    info.path,
                    info.name,
                    info.sha256,
                    info.size,
                    info.mtime,
                    info.pages,
                    info.total_pages,
                    info.status.value,
                    info.doc_type,
                    info.engine,
                    info.error,
                    info.mean_conf,
                    added,
                ),
            )

    def get_document(self, doc_id: str) -> DocumentInfo | None:
        rows = self._all("SELECT * FROM documents WHERE id = ?", (doc_id,))
        return self._doc(rows[0]) if rows else None

    def find_ready_by_hash(self, sha256: str) -> DocumentInfo | None:
        rows = self._all("SELECT * FROM documents WHERE sha256 = ? AND status = 'ready' LIMIT 1", (sha256,))
        return self._doc(rows[0]) if rows else None

    def list_documents(self, status: DocStatus | None = None) -> list[DocumentInfo]:
        if status:
            rows = self._all("SELECT * FROM documents WHERE status = ? ORDER BY added_at DESC", (status.value,))
        else:
            rows = self._all("SELECT * FROM documents ORDER BY added_at DESC")
        return [self._doc(r) for r in rows]

    def delete_document(self, doc_id: str) -> bool:
        with self.tx() as db:
            cur = db.execute("DELETE FROM documents WHERE id = ?", (doc_id,))
        return cur.rowcount > 0

    # -- content -----------------------------------------------------------

    def save_content(
        self, doc_id: str, content: DocumentContent, chunks: list[Chunk], flagged: set[int], store_text: bool = True
    ) -> None:
        with self.tx() as db:
            for table in ("pages", "blocks", "chunks"):
                db.execute(f"DELETE FROM {table} WHERE doc_id = ?", (doc_id,))
            for p in content.pages:
                lines = [ln.model_dump() for ln in p.lines] if store_text else []
                db.execute(
                    "INSERT INTO pages VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        doc_id,
                        p.number,
                        p.width,
                        p.height,
                        p.source,
                        p.markdown if store_text else "",
                        json.dumps(lines),
                        p.mean_conf,
                        p.rotation,
                        p.note,
                        p.ocr_ms,
                    ),
                )
                db.executemany(
                    "INSERT INTO blocks VALUES (?,?,?,?,?,?,?)",
                    [
                        (doc_id, p.number, b.index, b.label, b.text if store_text else "", _j(b.bbox), b.conf)
                        for b in p.blocks
                    ],
                )
            db.executemany(
                "INSERT INTO chunks (doc_id, page, block_start, block_end, text, bbox, conf, flagged, search_text) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                [
                    (
                        doc_id,
                        c.page,
                        c.block_start,
                        c.block_end,
                        c.text,
                        _j(c.bbox),
                        c.conf,
                        int(i in flagged),
                        search_form(c.text),
                    )
                    for i, c in enumerate(chunks)
                ],
            )

    def copy_content(self, source_id: str, target_id: str) -> None:
        """Reuse already-extracted content for an identical file (same SHA-256)."""
        with self.tx() as db:
            for table in ("pages", "blocks", "chunks"):
                db.execute(f"DELETE FROM {table} WHERE doc_id = ?", (target_id,))
            db.execute(
                "INSERT INTO pages SELECT ?, number, width, height, source, markdown, lines, mean_conf, "
                "rotation, note, ocr_ms FROM pages WHERE doc_id = ?",
                (target_id, source_id),
            )
            db.execute(
                "INSERT INTO blocks SELECT ?, page, idx, label, text, bbox, conf FROM blocks WHERE doc_id = ?",
                (target_id, source_id),
            )
            db.execute(
                "INSERT INTO chunks (doc_id, page, block_start, block_end, text, bbox, conf, flagged, search_text) "
                "SELECT ?, page, block_start, block_end, text, bbox, conf, flagged, search_text FROM chunks "
                "WHERE doc_id = ? ORDER BY id",
                (target_id, source_id),
            )

    def get_pages(self, doc_id: str) -> list[PageContent]:
        rows = self._all("SELECT * FROM pages WHERE doc_id = ? ORDER BY number", (doc_id,))
        blocks = self.get_blocks(doc_id)
        by_page: dict[int, list[Block]] = {}
        for page, block in blocks:
            by_page.setdefault(page, []).append(block)
        return [
            PageContent(
                number=r["number"],
                width=r["width"],
                height=r["height"],
                source=r["source"] or "",
                markdown=r["markdown"] or "",
                lines=tuple(TextLine(**ln) for ln in json.loads(r["lines"] or "[]")),
                blocks=tuple(by_page.get(r["number"], [])),
                rotation=r["rotation"] or 0,
                note=r["note"] or "",
                ocr_ms=r["ocr_ms"],
            )
            for r in rows
        ]

    def get_blocks(self, doc_id: str) -> list[tuple[int, Block]]:
        rows = self._all("SELECT * FROM blocks WHERE doc_id = ? ORDER BY page, idx", (doc_id,))
        return [
            (r["page"], Block(index=r["idx"], label=r["label"], text=r["text"], bbox=_bbox(r["bbox"]), conf=r["conf"]))
            for r in rows
        ]

    def document_text(self, doc_id: str) -> str:
        rows = self._all("SELECT text FROM chunks WHERE doc_id = ? ORDER BY page, block_start", (doc_id,))
        return "\n".join(r["text"] for r in rows)

    def flagged_chunks(self, doc_ids: list[str] | None = None) -> list[sqlite3.Row]:
        rows = self._all("SELECT * FROM chunks WHERE flagged = 1")
        return [r for r in rows if doc_ids is None or r["doc_id"] in doc_ids]

    # -- retrieval ---------------------------------------------------------

    def _source(self, row: sqlite3.Row, score: float | None) -> Source:
        return Source(
            doc_id=row["doc_id"],
            path=row["path"],
            name=row["name"],
            page=row["page"],
            block=row["block_start"],
            bbox=_bbox(row["bbox"]),
            excerpt=row["text"],
            score=score,
            ocr_conf=row["conf"],
        )

    def keyword_search(self, query: str, doc_ids: list[str] | None, limit: int) -> list[tuple[int, Source]]:
        q = fts_query(query)
        if not q:
            return []
        sql = (
            "SELECT c.*, d.path, d.name, bm25(chunks_fts) AS rank FROM chunks_fts "
            "JOIN chunks c ON c.id = chunks_fts.rowid JOIN documents d ON d.id = c.doc_id "
            "WHERE chunks_fts MATCH ? AND d.status = 'ready'"
        )
        args: list[Any] = [q]
        if doc_ids is not None:
            if not doc_ids:
                return []
            sql += f" AND c.doc_id IN ({','.join('?' * len(doc_ids))})"
            args.extend(doc_ids)
        sql += " ORDER BY rank LIMIT ?"
        args.append(limit)
        try:
            rows = self._all(sql, tuple(args))
        except sqlite3.OperationalError:
            return []
        return [(r["id"], self._source(r, round(-float(r["rank"]), 4))) for r in rows]

    def clear_content(self, doc_id: str) -> None:
        with self.tx() as db:
            for table in ("pages", "blocks", "chunks"):
                db.execute(f"DELETE FROM {table} WHERE doc_id = ?", (doc_id,))

    def chunk_sources(self, chunk_ids: list[int]) -> dict[int, Source]:
        if not chunk_ids:
            return {}
        rows = self._all(
            f"SELECT c.*, d.path, d.name FROM chunks c JOIN documents d ON d.id = c.doc_id "
            f"WHERE c.id IN ({','.join('?' * len(chunk_ids))})",
            tuple(chunk_ids),
        )
        return {r["id"]: self._source(r, None) for r in rows}

    def chunks_for(self, doc_ids: list[str]) -> list[tuple[int, Source]]:
        if not doc_ids:
            return []
        rows = self._all(
            f"SELECT c.*, d.path, d.name FROM chunks c JOIN documents d ON d.id = c.doc_id "
            f"WHERE c.doc_id IN ({','.join('?' * len(doc_ids))}) ORDER BY c.doc_id, c.page, c.block_start",
            tuple(doc_ids),
        )
        return [(r["id"], self._source(r, None)) for r in rows]

    def missing_embeddings(self, model: str) -> list[tuple[int, str]]:
        rows = self._all(
            "SELECT c.id, c.text FROM chunks c LEFT JOIN embeddings e ON e.chunk_id = c.id "
            "AND e.model = ? WHERE e.chunk_id IS NULL",
            (model,),
        )
        return [(r["id"], r["text"]) for r in rows]

    def save_embeddings(self, model: str, items: list[tuple[int, np.ndarray]]) -> None:
        with self.tx() as db:
            db.executemany(
                "INSERT OR REPLACE INTO embeddings VALUES (?,?,?,?)",
                [(cid, model, int(v.shape[0]), v.astype(np.float32).tobytes()) for cid, v in items],
            )

    def embeddings(self, model: str, doc_ids: list[str] | None) -> tuple[list[int], np.ndarray]:
        sql = "SELECT e.chunk_id, e.vec FROM embeddings e JOIN chunks c ON c.id = e.chunk_id WHERE e.model = ?"
        args: list[Any] = [model]
        if doc_ids is not None:
            if not doc_ids:
                return [], np.zeros((0, 0), np.float32)
            sql += f" AND c.doc_id IN ({','.join('?' * len(doc_ids))})"
            args.extend(doc_ids)
        rows = self._all(sql, tuple(args))
        if not rows:
            return [], np.zeros((0, 0), np.float32)
        return [r["chunk_id"] for r in rows], np.stack([np.frombuffer(r["vec"], np.float32) for r in rows])

    # -- tasks -------------------------------------------------------------

    def save_task(self, result: AgentResult) -> None:
        with self.tx() as db:
            db.execute(
                "INSERT OR REPLACE INTO tasks VALUES (?,?,?,?,?,?,?)",
                (
                    result.task_id,
                    result.request,
                    result.intent,
                    result.state.value,
                    datetime.now(UTC).isoformat(),
                    result.duration_ms,
                    result.model_dump_json(),
                ),
            )

    def list_tasks(self, limit: int = 50) -> list[dict[str, Any]]:
        rows = self._all(
            "SELECT id, request, intent, state, created_at, duration_ms FROM tasks ORDER BY created_at DESC LIMIT ?",
            (limit,),
        )
        return [dict(r) for r in rows]

    def get_task(self, task_id: str) -> AgentResult | None:
        rows = self._all("SELECT result FROM tasks WHERE id = ?", (task_id,))
        return AgentResult.model_validate_json(rows[0]["result"]) if rows else None

    def clear_tasks(self) -> int:
        with self.tx() as db:
            return db.execute("DELETE FROM tasks").rowcount

    def stats(self) -> dict[str, int]:
        out = {}
        for table in ("documents", "pages", "chunks", "embeddings", "tasks"):
            out[table] = self._all(f"SELECT COUNT(*) AS n FROM {table}")[0]["n"]
        return out
